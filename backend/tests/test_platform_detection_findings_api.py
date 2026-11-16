import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from app.models import (
    PlatformDetectionFinding,
    PlatformDetectionFindingEvent,
    PlatformOperator,
    User,
)


@pytest.fixture
def api_context(monkeypatch):
    import app.main as main_module
    import app.database.session as session_module

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

    monkeypatch.setattr(main_module, "engine", test_engine)
    monkeypatch.setattr(session_module, "engine", test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "session_factory": TestingSessionLocal,
            }
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def register_and_login(client, email="platform-test@example.com"):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "StrongPassphrase123!",
            "organization_name": "Platform Detection Test Organization",
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


def create_finding(
    session_factory,
    status="open",
    rule_id="AUTH_IP_BURST",
):
    from datetime import datetime, timezone
    import uuid

    now = datetime.now(timezone.utc)

    with session_factory() as db:
        finding = PlatformDetectionFinding(
            id=str(uuid.uuid4()),
            rule_id=rule_id,
            deduplication_key=str(uuid.uuid4()),
            severity="high",
            status=status,
            title="Repeated failed login attempts",
            description="Multiple failed login attempts from one source.",
            evidence={
                "source_ip": "192.0.2.10",
                "signal_ids": ["test-signal-1"],
            },
            first_detected_at=now,
            last_detected_at=now,
            occurrence_count=10,
        )

        db.add(finding)
        db.commit()
        db.refresh(finding)

        return finding.id


def test_findings_require_authentication(api_context):
    response = api_context["client"].get(
        "/api/v1/platform/detections"
    )

    assert response.status_code == 401


def test_organization_user_cannot_access_platform_findings(api_context):
    client = api_context["client"]
    headers = register_and_login(
        client,
        "ordinary-detection-user@example.com",
    )

    assert client.get(
        "/api/v1/platform/detections",
        headers=headers,
    ).status_code == 403


def test_active_operator_can_list_findings(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "list-operator@example.com"
    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    finding_id = create_finding(session_factory)

    response = client.get(
        "/api/v1/platform/detections",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == finding_id


def test_finding_list_supports_filters_and_pagination(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "filter-operator@example.com"
    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    create_finding(session_factory, "open", "AUTH_IP_BURST")
    create_finding(session_factory, "resolved", "AUTH_ACCOUNT_BURST")

    response = client.get(
        "/api/v1/platform/detections",
        params={
            "status": "open",
            "severity": "high",
            "limit": 1,
            "offset": 0,
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert len(response.json()["items"]) == 1


def test_invalid_status_filter_is_rejected(api_context):
    client = api_context["client"]
    email = "invalid-filter-operator@example.com"

    headers = register_and_login(client, email)
    grant_platform_operator(api_context["session_factory"], email)

    response = client.get(
        "/api/v1/platform/detections",
        params={"status": "unknown"},
        headers=headers,
    )

    assert response.status_code == 422


def test_operator_can_view_finding_details(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "detail-operator@example.com"
    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    finding_id = create_finding(session_factory)

    response = client.get(
        f"/api/v1/platform/detections/{finding_id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == finding_id
    assert response.json()["status"] == "open"
    assert response.json()["events"] == []


def test_unknown_finding_returns_404(api_context):
    client = api_context["client"]
    email = "missing-operator@example.com"

    headers = register_and_login(client, email)
    grant_platform_operator(api_context["session_factory"], email)

    response = client.get(
        "/api/v1/platform/detections/nonexistent",
        headers=headers,
    )

    assert response.status_code == 404


def test_operator_can_acknowledge_finding(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "ack-operator@example.com"
    headers = register_and_login(client, email)
    operator_id = grant_platform_operator(session_factory, email)

    finding_id = create_finding(session_factory)

    response = client.post(
        f"/api/v1/platform/detections/{finding_id}/acknowledge",
        headers=headers,
        json={"reason": "Security team has started reviewing."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "acknowledged"

    with session_factory() as db:
        event = (
            db.query(PlatformDetectionFindingEvent)
            .filter(
                PlatformDetectionFindingEvent.finding_id == finding_id
            )
            .one()
        )

        assert event.event_type == "acknowledged"
        assert event.reason == "Security team has started reviewing."
        assert event.details["actor_operator_id"] == operator_id
        assert event.details["previous_status"] == "open"
        assert event.details["new_status"] == "acknowledged"


def test_operator_can_resolve_open_finding(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "resolve-operator@example.com"
    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    finding_id = create_finding(session_factory)

    response = client.post(
        f"/api/v1/platform/detections/{finding_id}/resolve",
        headers=headers,
        json={"reason": "Investigation completed and documented."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"

    with session_factory() as db:
        event = (
            db.query(PlatformDetectionFindingEvent)
            .filter(
                PlatformDetectionFindingEvent.finding_id == finding_id
            )
            .one()
        )

        assert event.event_type == "resolved"


def test_operator_can_resolve_acknowledged_finding(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "resolve-ack-operator@example.com"
    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    finding_id = create_finding(
        session_factory,
        status="acknowledged",
    )

    response = client.post(
        f"/api/v1/platform/detections/{finding_id}/resolve",
        headers=headers,
        json={"reason": "Investigation completed and documented."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_invalid_transition_is_rejected_without_event(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "transition-operator@example.com"
    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    finding_id = create_finding(
        session_factory,
        status="acknowledged",
    )

    response = client.post(
        f"/api/v1/platform/detections/{finding_id}/acknowledge",
        headers=headers,
        json={"reason": "Reviewing the security incident."},
    )

    assert response.status_code == 409

    with session_factory() as db:
        finding = db.query(PlatformDetectionFinding).filter(
            PlatformDetectionFinding.id == finding_id
        ).one()

        assert finding.status == "acknowledged"
        assert db.query(PlatformDetectionFindingEvent).count() == 0


@pytest.mark.parametrize(
    "reason",
    ["", "    ", "bad", "x" * 1001],
)
def test_invalid_status_change_reasons_are_rejected(api_context, reason):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "invalid-reason-operator@example.com"
    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    finding_id = create_finding(session_factory)

    response = client.post(
        f"/api/v1/platform/detections/{finding_id}/acknowledge",
        headers=headers,
        json={"reason": reason},
    )

    assert response.status_code == 422

    with session_factory() as db:
        finding = db.query(PlatformDetectionFinding).filter(
            PlatformDetectionFinding.id == finding_id
        ).one()

        assert finding.status == "open"
        assert db.query(PlatformDetectionFindingEvent).count() == 0


def test_status_change_reason_is_trimmed(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "trim-operator@example.com"
    headers = register_and_login(client, email)
    grant_platform_operator(session_factory, email)

    finding_id = create_finding(session_factory)

    response = client.post(
        f"/api/v1/platform/detections/{finding_id}/acknowledge",
        headers=headers,
        json={"reason": "   Security review started.   "},
    )

    assert response.status_code == 200

    with session_factory() as db:
        event = db.query(PlatformDetectionFindingEvent).one()
        assert event.reason == "Security review started."


def test_inactive_operator_cannot_change_finding_status(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "inactive-operator@example.com"
    headers = register_and_login(client, email)
    operator_id = grant_platform_operator(session_factory, email)

    finding_id = create_finding(session_factory)

    with session_factory() as db:
        operator = db.query(PlatformOperator).filter(
            PlatformOperator.id == operator_id
        ).one()
        operator.is_active = False
        db.commit()

    response = client.post(
        f"/api/v1/platform/detections/{finding_id}/acknowledge",
        headers=headers,
        json={"reason": "Reviewing the security incident."},
    )

    assert response.status_code == 403

    with session_factory() as db:
        finding = db.query(PlatformDetectionFinding).filter(
            PlatformDetectionFinding.id == finding_id
        ).one()

        assert finding.status == "open"
        assert db.query(PlatformDetectionFindingEvent).count() == 0


def test_inactive_operator_cannot_list_findings(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    email = "inactive-list-operator@example.com"
    headers = register_and_login(client, email)
    operator_id = grant_platform_operator(session_factory, email)

    with session_factory() as db:
        operator = db.query(PlatformOperator).filter(
            PlatformOperator.id == operator_id
        ).one()
        operator.is_active = False
        db.commit()

    response = client.get(
        "/api/v1/platform/detections",
        headers=headers,
    )

    assert response.status_code == 403


def test_finding_lifecycle_events_are_append_only(api_context):
    session_factory = api_context["session_factory"]

    finding_id = create_finding(session_factory)

    with session_factory() as db:
        event = PlatformDetectionFindingEvent(
            finding_id=finding_id,
            event_type="detected",
            reason="Test detection event.",
            details={"source": "test"},
        )
        db.add(event)
        db.commit()
        event_id = event.id

    with session_factory() as db:
        event = db.query(PlatformDetectionFindingEvent).filter(
            PlatformDetectionFindingEvent.id == event_id
        ).one()

        event.reason = "Attempted modification."
        with pytest.raises(Exception):
            db.commit()
        db.rollback()

    with session_factory() as db:
        event = db.query(PlatformDetectionFindingEvent).filter(
            PlatformDetectionFindingEvent.id == event_id
        ).one()

        assert event.reason == "Test detection event."

        with pytest.raises(Exception):
            db.delete(event)
            db.commit()

        db.rollback()


def test_ordinary_user_cannot_acknowledge_finding(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    headers = register_and_login(
        client,
        "ordinary-ack-user@example.com",
    )
    finding_id = create_finding(session_factory)

    response = client.post(
        f"/api/v1/platform/detections/{finding_id}/acknowledge",
        headers=headers,
        json={"reason": "Unauthorized review attempt."},
    )

    assert response.status_code == 403


def test_ordinary_user_cannot_resolve_finding(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    headers = register_and_login(
        client,
        "ordinary-resolve-user@example.com",
    )
    finding_id = create_finding(session_factory)

    response = client.post(
        f"/api/v1/platform/detections/{finding_id}/resolve",
        headers=headers,
        json={"reason": "Unauthorized resolution attempt."},
    )

    assert response.status_code == 403
