import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from app.models import Asset, Membership


@pytest.fixture
def api_context():
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

    with TestClient(app) as client:
        yield {
            "client": client,
            "session_factory": TestingSessionLocal,
        }

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def setup_account(client, email="execution@example.com"):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "StrongPassphrase123!",
            "organization_name": "Execution Test Organization",
        },
    )
    assert registration.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "StrongPassphrase123!",
        },
    )
    assert login.status_code == 200

    return {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }


def setup_asset(client, headers):
    response = client.post(
        "/api/v1/assets",
        headers=headers,
        json={
            "name": "Execution Test Server",
            "asset_type": "server",
            "identifier": "execution-server.local",
            "authorization_reference": "EXEC-AUTH-001",
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def verify_asset(session_factory, asset_id):
    with session_factory() as db:
        asset = db.query(Asset).filter(
            Asset.id == asset_id
        ).first()

        assert asset is not None
        asset.authorization_status = "verified"
        asset.assessment_enabled = True
        db.commit()


def setup_approved_action(client, headers, asset_id):
    mission_response = client.post(
        "/api/v1/missions",
        headers=headers,
        json={
            "title": "Execution API Test Mission",
            "objective": "Test the controlled execution queue.",
            "priority": "normal",
            "asset_id": asset_id,
        },
    )
    assert mission_response.status_code == 201

    mission_id = mission_response.json()["id"]

    proposal = client.post(
        f"/api/v1/missions/{mission_id}/actions",
        headers=headers,
        json={
            "action_type": "collect_inventory",
            "target_id": asset_id,
            "description": "Collect authorized asset inventory.",
        },
    )
    assert proposal.status_code == 201

    action_id = proposal.json()["id"]

    approval = client.post(
        f"/api/v1/actions/{action_id}/decision",
        headers=headers,
        json={
            "decision": "approve",
            "reason": "Approved for isolated API testing.",
        },
    )
    assert approval.status_code == 200

    return action_id


def prepare_approved_action(context, verify=True):
    client = context["client"]
    session_factory = context["session_factory"]

    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    if verify:
        verify_asset(session_factory, asset_id)

    action_id = setup_approved_action(
        client,
        headers,
        asset_id,
    )

    return headers, action_id


def test_approved_action_is_queued_without_execution(api_context):
    client = api_context["client"]

    headers, action_id = prepare_approved_action(api_context)

    response = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )

    assert response.status_code == 201

    data = response.json()
    assert data["action_request_id"] == action_id
    assert data["status"] == "queued"
    assert data["verified"] is False
    assert data["result"]["mode"] == "queued_only"
    assert data["result"]["execution_started"] is False

    listing = client.get(
        "/api/v1/executions",
        headers=headers,
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = client.get(
        f"/api/v1/executions/{data['id']}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == data["id"]


def test_unverified_asset_cannot_be_queued(api_context):
    client = api_context["client"]

    headers, action_id = prepare_approved_action(
        api_context,
        verify=False,
    )

    response = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )

    assert response.status_code == 409
    assert client.get(
        "/api/v1/executions",
        headers=headers,
    ).json() == []


def test_queue_requires_authentication(api_context):
    client = api_context["client"]

    headers, action_id = prepare_approved_action(api_context)

    response = client.post(
        f"/api/v1/actions/{action_id}/queue",
    )

    assert response.status_code == 401


def test_unknown_action_cannot_be_queued(api_context):
    client = api_context["client"]
    headers = setup_account(client)

    response = client.post(
        "/api/v1/actions/unknown-action-id/queue",
        headers=headers,
    )

    assert response.status_code == 404


def test_duplicate_queue_request_returns_same_record(api_context):
    client = api_context["client"]

    headers, action_id = prepare_approved_action(api_context)

    first = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )
    second = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listing = client.get(
        "/api/v1/executions",
        headers=headers,
    )

    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_non_admin_cannot_queue_action(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    headers, action_id = prepare_approved_action(api_context)

    with session_factory() as db:
        membership = db.query(Membership).first()
        assert membership is not None
        membership.role = "member"
        db.commit()

    response = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )

    assert response.status_code == 403


def test_execution_record_is_hidden_from_other_organization(api_context):
    client = api_context["client"]

    headers_one, action_id = prepare_approved_action(api_context)

    queued = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers_one,
    )
    assert queued.status_code == 201

    headers_two = setup_account(
        client,
        email="other-organization@example.com",
    )

    listing = client.get(
        "/api/v1/executions",
        headers=headers_two,
    )
    assert listing.status_code == 200
    assert listing.json() == []

    detail = client.get(
        f"/api/v1/executions/{queued.json()['id']}",
        headers=headers_two,
    )
    assert detail.status_code == 404
