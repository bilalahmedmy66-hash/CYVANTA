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
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def register_and_login(client):
    email = "agent-registry@example.com"
    password = "StrongPassphrase123!"

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "organization_name": "Agent Registry Test Org",
        },
    )
    assert registration.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200

    return {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }


def test_agent_registry_requires_authentication(client):
    response = client.get("/api/v1/agent-intelligence/registry")
    assert response.status_code == 401


def test_agent_registry_returns_expected_identity_counts(client):
    headers = register_and_login(client)

    response = client.get(
        "/api/v1/agent-intelligence/registry",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["summary"]["registered_identities"] == 211
    assert payload["summary"]["global_coordinators"] == 1
    assert payload["summary"]["layer_coordinators"] == 10
    assert payload["summary"]["specialists"] == 200
    assert payload["summary"]["layers"] == 10
    assert payload["summary"]["running_workers"] is None
    assert len(payload["agents"]) == 211
    assert len(payload["layers"]) == 10


def test_agent_registry_preserves_advisory_only_boundary(client):
    headers = register_and_login(client)

    response = client.get(
        "/api/v1/agent-intelligence/registry",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["metadata_only"] is True
    assert payload["execution_model"] == (
        "logical_identities_not_persistent_workers"
    )
    assert payload["safety_boundary"]["permission_profile"] == "advisory_only"
    assert payload["safety_boundary"]["security_actions_enabled"] is False
    assert payload["safety_boundary"]["agent_execution_enabled"] is False

    for agent in payload["agents"]:
        assert agent["status"] == "registered"
        assert agent["permission_profile"] == "advisory_only"
        assert agent["capabilities"] == ["observe", "analyze", "propose"]
        assert "execute" not in agent["capabilities"]


def test_agent_registry_exposes_valid_hierarchy(client):
    headers = register_and_login(client)

    response = client.get(
        "/api/v1/agent-intelligence/registry",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()

    global_id = payload["global_coordinator"]["agent_id"]
    assert global_id == "CYV-GLOBAL-COORD-001"
    assert payload["global_coordinator"]["coordinator_id"] is None

    for layer in payload["layers"]:
        assert layer["specialist_count"] == 20

        coordinator = next(
            agent for agent in payload["agents"]
            if agent["agent_id"] == layer["coordinator_id"]
        )
        assert coordinator["agent_type"] == "layer_coordinator"
        assert coordinator["coordinator_id"] == global_id

        specialists = [
            agent for agent in payload["agents"]
            if agent["agent_type"] == "specialist"
            and agent["layer_id"] == layer["layer_id"]
        ]
        assert len(specialists) == 20
        assert all(
            agent["coordinator_id"] == coordinator["agent_id"]
            for agent in specialists
        )