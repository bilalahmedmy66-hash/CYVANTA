import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=test_engine)

    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def register_user(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@example.com",
            "password": "StrongPassphrase123!",
            "organization_name": "CYVANTA Test Organization",
        },
    )
    return response


def login_user(client):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "StrongPassphrase123!",
        },
    )
    return response.json()["access_token"]


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["application"] == "CYVANTA"


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_system_info_endpoint(client):
    response = client.get("/api/v1/system/info")
    assert response.status_code == 200
    assert response.json()["version"] == "0.1.0"


def test_user_registration(client):
    response = register_user(client)

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "admin@example.com"
    assert response.json()["organization_name"] == "CYVANTA Test Organization"
    assert "password_hash" not in response.json()["user"]


def test_duplicate_registration(client):
    register_user(client)

    response = register_user(client)

    assert response.status_code == 409


def test_user_login(client):
    register_user(client)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "StrongPassphrase123!",
        },
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_protected_profile(client):
    register_user(client)
    token = login_user(client)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"


def test_profile_rejects_unauthenticated_user(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_asset_registration(client):
    register_user(client)
    token = login_user(client)

    response = client.post(
        "/api/v1/assets",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "My Test Server",
            "asset_type": "server",
            "identifier": "test-server.local",
            "authorization_reference": "LAB-AUTH-001",
            "authorization_confirmed": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["authorization_status"] == "declared"
    assert response.json()["assessment_enabled"] is False


def test_asset_registration_requires_authorization(client):
    register_user(client)
    token = login_user(client)

    response = client.post(
        "/api/v1/assets",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Unapproved Server",
            "asset_type": "server",
            "identifier": "server.example.test",
            "authorization_reference": "LAB-AUTH-002",
            "authorization_confirmed": False,
        },
    )

    assert response.status_code == 400
