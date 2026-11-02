import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from app.models import (
    AuditLog,
    EmergencyStopState,
    Membership,
)


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


def setup_account(client, email="emergency@example.com"):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "StrongPassphrase123!",
            "organization_name": "Emergency Stop Test Organization",
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


def test_emergency_stop_is_inactive_by_default(api_context):
    client = api_context["client"]
    headers = setup_account(client)

    response = client.get(
        "/api/v1/emergency-stop",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["organization_id"] is not None


def test_owner_can_activate_emergency_stop(api_context):
    client = api_context["client"]
    headers = setup_account(client)

    response = client.post(
        "/api/v1/emergency-stop/activate",
        headers=headers,
        json={"reason": "Suspicious activity detected."},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert response.json()["reason"] == "Suspicious activity detected."
    assert response.json()["changed_by"] is not None

    status = client.get(
        "/api/v1/emergency-stop",
        headers=headers,
    )

    assert status.status_code == 200
    assert status.json()["is_active"] is True


def test_owner_can_deactivate_emergency_stop(api_context):
    client = api_context["client"]
    headers = setup_account(client)

    activated = client.post(
        "/api/v1/emergency-stop/activate",
        headers=headers,
        json={"reason": "Testing activation."},
    )

    assert activated.status_code == 200
    assert activated.json()["is_active"] is True

    deactivated = client.post(
        "/api/v1/emergency-stop/deactivate",
        headers=headers,
        json={"reason": "Incident has been reviewed."},
    )

    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert deactivated.json()["reason"] == "Incident has been reviewed."


def test_member_cannot_change_emergency_stop(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    headers = setup_account(client)

    with session_factory() as db:
        membership = db.query(Membership).first()
        assert membership is not None
        membership.role = "member"
        db.commit()

    activate = client.post(
        "/api/v1/emergency-stop/activate",
        headers=headers,
        json={"reason": "Unauthorized activation attempt."},
    )

    deactivate = client.post(
        "/api/v1/emergency-stop/deactivate",
        headers=headers,
        json={"reason": "Unauthorized deactivation attempt."},
    )

    assert activate.status_code == 403
    assert deactivate.status_code == 403


def test_emergency_stop_is_isolated_between_organizations(api_context):
    client = api_context["client"]

    headers_one = setup_account(
        client,
        email="organization-one@example.com",
    )

    headers_two = setup_account(
        client,
        email="organization-two@example.com",
    )

    activated = client.post(
        "/api/v1/emergency-stop/activate",
        headers=headers_one,
        json={"reason": "Organization one incident."},
    )

    assert activated.status_code == 200

    status_one = client.get(
        "/api/v1/emergency-stop",
        headers=headers_one,
    )

    status_two = client.get(
        "/api/v1/emergency-stop",
        headers=headers_two,
    )

    assert status_one.status_code == 200
    assert status_two.status_code == 200

    assert status_one.json()["is_active"] is True
    assert status_two.json()["is_active"] is False

    assert (
        status_one.json()["organization_id"]
        != status_two.json()["organization_id"]
    )


def test_blank_emergency_stop_reason_is_rejected(api_context):
    client = api_context["client"]
    headers = setup_account(client)

    response = client.post(
        "/api/v1/emergency-stop/activate",
        headers=headers,
        json={"reason": "     "},
    )

    assert response.status_code == 422

    status = client.get(
        "/api/v1/emergency-stop",
        headers=headers,
    )

    assert status.status_code == 200
    assert status.json()["is_active"] is False


def test_emergency_stop_and_audit_records_persist_across_sessions(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    headers = setup_account(client)

    activated = client.post(
        "/api/v1/emergency-stop/activate",
        headers=headers,
        json={"reason": "Persistence verification test."},
    )

    assert activated.status_code == 200

    state_id = None
    organization_id = activated.json()["organization_id"]

    with session_factory() as db:
        state = (
            db.query(EmergencyStopState)
            .filter(
                EmergencyStopState.organization_id == organization_id
            )
            .first()
        )

        assert state is not None
        assert state.is_active is True
        state_id = state.id

    # A separate session verifies that the state remains stored.
    with session_factory() as db:
        state = db.query(EmergencyStopState).filter(
            EmergencyStopState.id == state_id
        ).first()

        assert state is not None
        assert state.is_active is True

        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.organization_id == organization_id,
                AuditLog.action == "emergency_stop.activated",
            )
            .first()
        )

        assert audit is not None
        assert audit.target_id == state.id
        assert audit.details["reason"] == "Persistence verification test."
