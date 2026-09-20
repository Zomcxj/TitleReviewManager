import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def create_test_customer(client: TestClient, token_cookie: str):
    return client.post(
        "/api/customers/",
        json={
            "name": "Test Customer",
            "id_number": "110101199001011237",
            "phone": "13800138000",
            "education": "本科",
            "current_title": "无",
            "target_title": "中级工程师",
            "work_unit": "Test Corp",
            "position": "Engineer",
            "professional_years": 5,
            "project_experiences": "[]"
        },
        cookies={"access_token": token_cookie}
    )

def test_create_customer(client: TestClient, test_user):
    login_resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpassword"})
    token = login_resp.cookies.get("access_token")
    
    response = create_test_customer(client, token)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Customer"
    assert data["id_number"] == "110101199001011237"
    assert "id" in data

def test_read_customers(client: TestClient, test_user):
    login_resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpassword"})
    token = login_resp.cookies.get("access_token")
    
    create_test_customer(client, token)
    
    response = client.get("/api/customers/", cookies={"access_token": token})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["items"], list)
    assert len(data["items"]) > 0
    assert data["items"][0]["name"] == "Test Customer"

def test_read_customer(client: TestClient, test_user):
    login_resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpassword"})
    token = login_resp.cookies.get("access_token")
    
    create_resp = create_test_customer(client, token)
    customer_id = create_resp.json()["id"]
    
    response = client.get(f"/api/customers/{customer_id}", cookies={"access_token": token})
    assert response.status_code == 200
    assert response.json()["name"] == "Test Customer"
