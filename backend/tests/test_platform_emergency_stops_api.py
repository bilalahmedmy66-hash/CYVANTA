import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from app.models import (
    PlatformEmergencyStopEvent,
    PlatformEmergencyStopState,
    PlatformOperator,
    User,
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


def register_and_login(client, email="platform-test@example.com"):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "StrongPassphrase123!",
            "organization_name": "Platform API Test Organization",
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


def grant_platform_operator(session_factory, email):
    with session_factory() as db:
        user = db.query(User).filter(User.email == email).one()
        operator = PlatformOperator(
            user_id=user.id,
            is_active=True,
            grant_reason="Test-only platform operator authorization.",
        )
        db.add(operator)
        db.commit()
        db.refresh(operator)
        return operator.id


def test_platform_status_requires_authentication(api_context):
    client = api_context["client"]

    response = client.get("/api/v1/platform/emergency-stop")

    assert response.status_code == 401


def test_organization_owner_without_platform_role_is_denied(api_context):
    client = api_context["client"]
    headers = register_and_login(client)

    response = client.get(
        "/api/v1/platform/emergency-stop",
        headers=headers,
    )

    assert response.status_code == 403


def test_platform_status_requires_active_operator(api_context):
    client = api_context["client"]
    email = "active-operator@example.com"
    headers = register_and_login(client, email)
    grant_platform_operator(api_context["session_factory"], email)

    response = client.get(
        "/api/v1/platform/emergency-stop",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert response.json()["reason"] is None


def test_platform_operator_can_activate_master_stop(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]
    email = "activate-operator@example.com"

    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    response = client.post(
        "/api/v1/platform/emergency-stop/activate",
        headers=headers,
        json={"reason": "Critical platform security incident."},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert response.json()["reason"] == "Critical platform security incident."

    with session_factory() as db:
        state = db.query(PlatformEmergencyStopState).one()
        event = (
            db.query(PlatformEmergencyStopEvent)
            .filter(PlatformEmergencyStopEvent.event_type == "activated")
            .one()
        )

        assert state.id == "platform-master"
        assert state.is_active is True
        assert event.reason == "Critical platform security incident."
        assert event.operator_id == state.changed_by_operator_id


def test_platform_operator_can_deactivate_master_stop(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]
    email = "deactivate-operator@example.com"

    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    activated = client.post(
        "/api/v1/platform/emergency-stop/activate",
        headers=headers,
        json={"reason": "Testing platform stop activation."},
    )

    assert activated.status_code == 200

    deactivated = client.post(
        "/api/v1/platform/emergency-stop/deactivate",
        headers=headers,
        json={"reason": "Platform incident review completed."},
    )

    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert deactivated.json()["reason"] == "Platform incident review completed."

    with session_factory() as db:
        events = (
            db.query(PlatformEmergencyStopEvent)
            .order_by(PlatformEmergencyStopEvent.created_at)
            .all()
        )

        assert len(events) == 2
        assert {event.event_type for event in events} == {
            "activated",
            "deactivated",
        }


def test_inactive_platform_operator_is_denied_immediately(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]
    email = "revoked-operator@example.com"

    headers = register_and_login(client, email)
    operator_id = grant_platform_operator(session_factory, email)

    with session_factory() as db:
        operator = db.query(PlatformOperator).filter(
            PlatformOperator.id == operator_id
        ).one()
        operator.is_active = False
        db.commit()

    response = client.get(
        "/api/v1/platform/emergency-stop",
        headers=headers,
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "reason",
    ["", "    ", "bad", "x" * 1001],
)
def test_invalid_platform_stop_reasons_are_rejected(api_context, reason):
    client = api_context["client"]
    email = "invalid-reason@example.com"

    headers = register_and_login(client, email)
    grant_platform_operator(api_context["session_factory"], email)

    response = client.post(
        "/api/v1/platform/emergency-stop/activate",
        headers=headers,
        json={"reason": reason},
    )

    assert response.status_code == 422

    with api_context["session_factory"]() as db:
        assert db.query(PlatformEmergencyStopState).count() == 0
        assert db.query(PlatformEmergencyStopEvent).count() == 0


def test_platform_stop_reason_is_trimmed(api_context):
    client = api_context["client"]
    email = "trim-reason@example.com"

    headers = register_and_login(client, email)
    grant_platform_operator(api_context["session_factory"], email)

    response = client.post(
        "/api/v1/platform/emergency-stop/activate",
        headers=headers,
        json={"reason": "   Security incident verified.   "},
    )

    assert response.status_code == 200
    assert response.json()["reason"] == "Security incident verified."


def test_malformed_platform_state_returns_service_unavailable(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]
    email = "malformed-state@example.com"

    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    with session_factory() as db:
        db.add(
            PlatformEmergencyStopState(
                id="unexpected-state-id",
                is_active=False,
                reason="Malformed test state.",
            )
        )
        db.commit()

    response = client.get(
        "/api/v1/platform/emergency-stop",
        headers=headers,
    )

    assert response.status_code == 503


def test_unauthorized_user_cannot_activate_platform_stop(api_context):
    client = api_context["client"]
    headers = register_and_login(client, "ordinary-user@example.com")

    response = client.post(
        "/api/v1/platform/emergency-stop/activate",
        headers=headers,
        json={"reason": "Unauthorized activation attempt."},
    )

    assert response.status_code == 403

    with api_context["session_factory"]() as db:
        assert db.query(PlatformEmergencyStopState).count() == 0
        assert db.query(PlatformEmergencyStopEvent).count() == 0
