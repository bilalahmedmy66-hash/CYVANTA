from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["application"] == "CYVANTA"


def test_health_endpoint():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_system_info_endpoint():
    response = client.get("/api/v1/system/info")

    assert response.status_code == 200
    assert response.json()["application"] == "CYVANTA"
    assert response.json()["version"] == "0.1.0"
