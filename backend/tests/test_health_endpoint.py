"""Security and availability tests for the health check endpoints.

Background: the service has an internet-reachable address (customer
registration links), so the health endpoints' information exposure must be
tightened:
- /api/health is anonymously accessible (container HEALTHCHECK / external
  probes depend on it), but on error it may only give generic information —
  returning raw database exceptions to the public internet equals leaking
  infrastructure details.
- /api/health/detail exposes JWT key strength, storage paths, scheduler
  status, etc., and must require an admin login (previously anonymous access
  worked, and the Guide even taught users "no login needed").
"""
import pytest
from fastapi.testclient import TestClient


def test_basic_health_is_anonymous(client: TestClient):
    """/api/health must be anonymously accessible: Docker HEALTHCHECK and external probes carry no login state."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_basic_health_does_not_leak_db_error(client: TestClient, monkeypatch):
    """On database errors return generic information; never hand the raw exception (may contain hosts/paths) to the public internet."""
    class BoomSession:
        def execute(self, *_a, **_k):
            raise RuntimeError("psycopg2: connect to 10.0.0.8:5432 failed: password invalid")

        def close(self):
            pass

    monkeypatch.setattr("database.SessionLocal", lambda: BoomSession())
    response = client.get("/api/health")
    body = response.json()
    assert body["status"] == "error"
    assert body["database"] == "unavailable"
    assert "10.0.0.8" not in response.text, "异常原文泄漏到公网响应"
    assert "password" not in response.text


def test_detail_requires_login(client: TestClient):
    """Anonymous access to the config self-check must be rejected: it exposes key strength/storage paths and other infrastructure details."""
    response = client.get("/api/health/detail")
    assert response.status_code == 401


def test_detail_rejects_non_admin(client: TestClient, test_salesman):
    client.post(
        "/api/auth/login",
        json={"username": "testsalesman", "password": "salespassword"},
    )
    response = client.get("/api/health/detail")
    assert response.status_code == 403
    assert "管理员" in response.json()["detail"]


def test_detail_allows_admin(client: TestClient, test_user):
    """After admin login, direct browser access still works (cookie auth, ops habits unchanged)."""
    client.post("/api/auth/login", json={"username": "testuser", "password": "testpassword"})
    response = client.get("/api/health/detail")
    assert response.status_code == 200
    body = response.json()
    names = {c["name"] for c in body["checks"]}
    assert {"数据库", "JWT 密钥"} <= names
    assert body["status"] in ("ok", "warning")
