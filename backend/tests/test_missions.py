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


def setup_account(client):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "mission@example.com",
            "password": "StrongPassphrase123!",
            "organization_name": "Mission Test Organization",
        },
    )

    assert registration.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "mission@example.com",
            "password": "StrongPassphrase123!",
        },
    )

    token = login.json()["access_token"]

    return {
        "Authorization": f"Bearer {token}",
    }


def setup_asset(client, headers):
    response = client.post(
        "/api/v1/assets",
        headers=headers,
        json={
            "name": "Mission Test Server",
            "asset_type": "server",
            "identifier": "mission-server.local",
            "authorization_reference": "TEST-AUTH-001",
            "authorization_confirmed": True,
        },
    )

    assert response.status_code == 201

    return response.json()["id"]


def setup_mission(client, headers, asset_id):
    response = client.post(
        "/api/v1/missions",
        headers=headers,
        json={
            "title": "Server Security Investigation",
            "objective": (
                "Investigate the registered server and "
                "identify potential security weaknesses."
            ),
            "priority": "high",
            "asset_id": asset_id,
        },
    )

    assert response.status_code == 201

    return response.json()


def test_create_mission(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    mission = setup_mission(client, headers, asset_id)

    assert mission["status"] == "planned"
    assert mission["execution_mode"] == "planning_only"
    assert mission["asset_id"] == asset_id
    assert len(mission["tasks"]) == 4


def test_list_missions(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    setup_mission(client, headers, asset_id)

    response = client.get(
        "/api/v1/missions",
        headers=headers,
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_mission_details(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    mission = setup_mission(client, headers, asset_id)

    response = client.get(
        f"/api/v1/missions/{mission['id']}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["title"] == mission["title"]


def test_propose_action(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    mission = setup_mission(client, headers, asset_id)

    response = client.post(
        f"/api/v1/missions/{mission['id']}/actions",
        headers=headers,
        json={
            "action_type": "review_configuration",
            "target_id": asset_id,
            "description": "Review the server security configuration.",
        },
    )

    assert response.status_code == 201
    assert response.json()["risk_level"] == "low"
    assert response.json()["status"] == "pending_approval"


def test_approve_proposed_action(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    mission = setup_mission(client, headers, asset_id)

    proposal = client.post(
        f"/api/v1/missions/{mission['id']}/actions",
        headers=headers,
        json={
            "action_type": "review_configuration",
            "target_id": asset_id,
            "description": "Review the security configuration.",
        },
    )

    action_id = proposal.json()["id"]

    response = client.post(
        f"/api/v1/actions/{action_id}/decision",
        headers=headers,
        json={
            "decision": "approve",
            "reason": "Approved for the authorized test environment.",
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "approve"


def test_reject_duplicate_decision(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    mission = setup_mission(client, headers, asset_id)

    proposal = client.post(
        f"/api/v1/missions/{mission['id']}/actions",
        headers=headers,
        json={
            "action_type": "review_configuration",
            "target_id": asset_id,
            "description": "Review the server configuration.",
        },
    )

    action_id = proposal.json()["id"]

    first = client.post(
        f"/api/v1/actions/{action_id}/decision",
        headers=headers,
        json={
            "decision": "approve",
            "reason": "Approved for testing.",
        },
    )

    second = client.post(
        f"/api/v1/actions/{action_id}/decision",
        headers=headers,
        json={
            "decision": "reject",
            "reason": "Attempting a second decision.",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_mission_rejects_unknown_asset(client):
    headers = setup_account(client)

    response = client.post(
        "/api/v1/missions",
        headers=headers,
        json={
            "title": "Invalid Asset Mission",
            "objective": "Investigate an unregistered asset.",
            "priority": "normal",
            "asset_id": "unknown-asset-id",
        },
    )

    assert response.status_code == 404


def test_action_rejects_unknown_target(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)
    mission = setup_mission(client, headers, asset_id)

    response = client.post(
        f"/api/v1/missions/{mission['id']}/actions",
        headers=headers,
        json={
            "action_type": "review_configuration",
            "target_id": "unknown-asset-id",
            "description": "Review an unregistered server.",
        },
    )

    assert response.status_code == 404
