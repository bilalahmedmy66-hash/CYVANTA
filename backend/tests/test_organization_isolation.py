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

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def register_account(client, email, organization_name):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "StrongPassphrase123!",
            "organization_name": organization_name,
        },
    )
    assert registration.status_code == 201, registration.text

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "StrongPassphrase123!",
        },
    )
    assert login.status_code == 200, login.text

    return {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }


def create_asset(client, headers, name, identifier):
    response = client.post(
        "/api/v1/assets",
        headers=headers,
        json={
            "name": name,
            "asset_type": "server",
            "identifier": identifier,
            "authorization_reference": "TEST-AUTH-001",
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_mission(client, headers, asset_id, title):
    response = client.post(
        "/api/v1/missions",
        headers=headers,
        json={
            "title": title,
            "objective": "Review the registered server security configuration.",
            "priority": "normal",
            "asset_id": asset_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_action(client, headers, mission_id, asset_id):
    response = client.post(
        f"/api/v1/missions/{mission_id}/actions",
        headers=headers,
        json={
            "action_type": "review_configuration",
            "target_id": asset_id,
            "description": "Review the authorized server configuration.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_asset_listing_is_isolated_between_organizations(client):
    headers_a = register_account(
        client, "asset-a@example.com", "Asset Organization A"
    )
    headers_b = register_account(
        client, "asset-b@example.com", "Asset Organization B"
    )

    create_asset(client, headers_a, "Organization A Server", "server-a.local")
    create_asset(client, headers_b, "Organization B Server", "server-b.local")

    response_a = client.get("/api/v1/assets", headers=headers_a)
    response_b = client.get("/api/v1/assets", headers=headers_b)

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    names_a = {asset["name"] for asset in response_a.json()}
    names_b = {asset["name"] for asset in response_b.json()}

    assert names_a == {"Organization A Server"}
    assert names_b == {"Organization B Server"}


def test_mission_listing_and_detail_are_isolated(client):
    headers_a = register_account(
        client, "mission-a@example.com", "Mission Organization A"
    )
    headers_b = register_account(
        client, "mission-b@example.com", "Mission Organization B"
    )

    asset_a = create_asset(
        client, headers_a, "Mission A Server", "mission-a.local"
    )
    mission_a = create_mission(
        client, headers_a, asset_a, "Organization A Mission"
    )

    asset_b = create_asset(
        client, headers_b, "Mission B Server", "mission-b.local"
    )
    mission_b = create_mission(
        client, headers_b, asset_b, "Organization B Mission"
    )

    list_a = client.get("/api/v1/missions", headers=headers_a)
    list_b = client.get("/api/v1/missions", headers=headers_b)

    assert list_a.status_code == 200
    assert list_b.status_code == 200

    assert [item["id"] for item in list_a.json()] == [mission_a["id"]]
    assert [item["id"] for item in list_b.json()] == [mission_b["id"]]

    foreign_detail = client.get(
        f"/api/v1/missions/{mission_a['id']}",
        headers=headers_b,
    )
    assert foreign_detail.status_code == 404


def test_mission_actions_are_isolated_between_organizations(client):
    headers_a = register_account(
        client, "actions-a@example.com", "Actions Organization A"
    )
    headers_b = register_account(
        client, "actions-b@example.com", "Actions Organization B"
    )

    asset_a = create_asset(
        client, headers_a, "Actions A Server", "actions-a.local"
    )
    mission_a = create_mission(
        client, headers_a, asset_a, "Organization A Action Mission"
    )

    action_a = create_action(
        client, headers_a, mission_a["id"], asset_a
    )

    foreign_proposal = client.post(
        f"/api/v1/missions/{mission_a['id']}/actions",
        headers=headers_b,
        json={
            "action_type": "review_configuration",
            "target_id": asset_a,
            "description": "Attempt to access another organization's mission.",
        },
    )
    assert foreign_proposal.status_code == 404

    foreign_listing = client.get(
        f"/api/v1/missions/{mission_a['id']}/actions",
        headers=headers_b,
    )
    assert foreign_listing.status_code == 404

    own_listing = client.get(
        f"/api/v1/missions/{mission_a['id']}/actions",
        headers=headers_a,
    )
    assert own_listing.status_code == 200
    assert [item["id"] for item in own_listing.json()] == [action_a["id"]]


def test_other_organization_cannot_decide_action(client):
    headers_a = register_account(
        client, "decision-a@example.com", "Decision Organization A"
    )
    headers_b = register_account(
        client, "decision-b@example.com", "Decision Organization B"
    )

    asset_a = create_asset(
        client, headers_a, "Decision A Server", "decision-a.local"
    )
    mission_a = create_mission(
        client, headers_a, asset_a, "Organization A Decision Mission"
    )
    action_a = create_action(
        client, headers_a, mission_a["id"], asset_a
    )

    foreign_decision = client.post(
        f"/api/v1/actions/{action_a['id']}/decision",
        headers=headers_b,
        json={
            "decision": "approve",
            "reason": "This decision must be rejected across organizations.",
        },
    )

    assert foreign_decision.status_code == 404

    owner_listing = client.get(
        f"/api/v1/missions/{mission_a['id']}/actions",
        headers=headers_a,
    )
    assert owner_listing.status_code == 200
    assert owner_listing.json()[0]["status"] == "pending_approval"
