"""健康检查端点的安全与可用性测试。

背景：服务有外网可达地址（客户注册链接），因此健康端点的信息暴露面必须收敛：
- /api/health 匿名可用（容器 HEALTHCHECK / 外部拨测依赖），但异常时只能给
  通用信息 —— 把数据库异常原文返回公网等于泄露基础设施细节。
- /api/health/detail 会暴露 JWT 密钥强度、存储路径、调度器状态等，
  必须管理员登录后才能访问（此前匿名可访问，Guide 还教用户「无需登录」）。
"""
import pytest
from fastapi.testclient import TestClient


def test_basic_health_is_anonymous(client: TestClient):
    """/api/health 必须匿名可用：Docker HEALTHCHECK 和外部拨测都没有登录态。"""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_basic_health_does_not_leak_db_error(client: TestClient, monkeypatch):
    """数据库异常时返回通用信息，不能把异常原文（可能含主机/路径）给公网。"""
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
    """匿名访问配置自检必须被拒：它暴露密钥强度/存储路径等基础设施信息。"""
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
    """管理员登录后浏览器直接访问仍可用（cookie 鉴权，运维习惯不变）。"""
    client.post("/api/auth/login", json={"username": "testuser", "password": "testpassword"})
    response = client.get("/api/health/detail")
    assert response.status_code == 200
    body = response.json()
    names = {c["name"] for c in body["checks"]}
    assert {"数据库", "JWT 密钥"} <= names
    assert body["status"] in ("ok", "warning")
