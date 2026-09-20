import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_login_success(client: TestClient, test_user):
    response = client.post("/api/auth/login", json={"username": "testuser", "password": "testpassword"})
    assert response.status_code == 200
    assert "access_token" in response.cookies
    data = response.json()
    assert data["user"]["username"] == "testuser"
    assert data["user"]["role"] == "admin"

def test_login_wrong_password(client: TestClient, test_user):
    response = client.post("/api/auth/login", json={"username": "testuser", "password": "wrongpassword"})
    assert response.status_code == 401
    assert response.json()["detail"] == "用户名或密码错误"

def test_login_nonexistent_user(client: TestClient):
    response = client.post("/api/auth/login", json={"username": "nonexistent", "password": "password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "用户名或密码错误"

def test_get_me(client: TestClient, test_user):
    client.post("/api/auth/login", json={"username": "testuser", "password": "testpassword"})
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert data["role"] == "admin"

def test_get_me_unauthorized(client: TestClient):
    response = client.get("/api/auth/me")
    assert response.status_code == 401

def test_logout(client: TestClient, test_user):
    client.post("/api/auth/login", json={"username": "testuser", "password": "testpassword"})
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert "access_token" not in response.cookies
