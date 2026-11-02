from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from app.models import Asset, AssetAuthorization, AuditLog, Membership, AuthorizationLifecycleEvent


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=test_engine)

    with test_engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TRIGGER prevent_authorization_lifecycle_update
            BEFORE UPDATE ON authorization_lifecycle_events
            BEGIN
                SELECT RAISE(ABORT, 'Authorization lifecycle events are append-only');
            END;
        """)
        connection.exec_driver_sql("""
            CREATE TRIGGER prevent_authorization_lifecycle_delete
            BEFORE DELETE ON authorization_lifecycle_events
            BEGIN
                SELECT RAISE(ABORT, 'Authorization lifecycle events are append-only');
            END;
        """)


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
            "email": "authorization@example.com",
            "password": "StrongPassphrase123!",
            "organization_name": "Authorization Test Organization",
        },
    )

    assert registration.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "authorization@example.com",
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
            "name": "Authorization Test Server",
            "asset_type": "server",
            "identifier": "authorization-server.example.test",
            "authorization_reference": "AUTH-TEST-001",
            "authorization_confirmed": True,
        },
    )

    assert response.status_code == 201
    return response.json()["id"]


def valid_authorization_payload():
    now = datetime.now(timezone.utc)

    return {
        "evidence_type": "authorization_letter",
        "evidence_reference": "EVIDENCE-REF-2026-001",
        "scope": {
            "domains": ["example.test"],
            "ip_addresses": ["192.0.2.10"],
            "excluded_targets": ["excluded.example.test"],
            "allowed_assessment_types": ["collect_inventory"],
        },
        "valid_from": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
    }


def submit_authorization(client, headers, asset_id, payload=None):
    if payload is None:
        payload = valid_authorization_payload()

    return client.post(
        f"/api/v1/assets/{asset_id}/authorizations",
        headers=headers,
        json=payload,
    )



def setup_reviewer(client, role="admin"):
    """Create a separate reviewer account in the original test organization."""
    from app.models import User, Organization
    from app.security.auth import hash_password

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "reviewer@example.com",
            "password": "StrongPassphrase123!",
            "organization_name": "Reviewer Temporary Organization",
        },
    )
    assert registration.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "reviewer@example.com",
            "password": "StrongPassphrase123!",
        },
    )
    assert login.status_code == 200

    # The reviewer account is moved into the original test organization.
    # This is test-only setup using the isolated in-memory database.
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        reviewer = db.query(User).filter(
            User.email == "reviewer@example.com"
        ).first()

        original_owner = db.query(User).filter(
            User.email == "authorization@example.com"
        ).first()

        if reviewer is None or original_owner is None:
            raise AssertionError("Test users could not be located.")

        original_membership = db.query(Membership).filter(
            Membership.user_id == original_owner.id
        ).first()

        if original_membership is None:
            raise AssertionError("Original organization membership missing.")

        temporary_memberships = db.query(Membership).filter(
            Membership.user_id == reviewer.id
        ).all()

        for item in temporary_memberships:
            db.delete(item)

        temporary_organizations = db.query(Organization).filter(
            Organization.name == "Reviewer Temporary Organization"
        ).all()

        for organization in temporary_organizations:
            db.delete(organization)

        db.add(
            Membership(
                user_id=reviewer.id,
                organization_id=original_membership.organization_id,
                role=role,
            )
        )
        db.commit()
    finally:
        db_generator.close()

    return {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }


def decide_authorization(client, headers, authorization_id, decision="approve"):
    return client.post(
        f"/api/v1/assets/authorizations/{authorization_id}/decision",
        headers=headers,
        json={
            "decision": decision,
            "reason": "Reviewed the authorization evidence and scope.",
        },
    )


def test_admin_can_approve_authorization_without_enabling_assessment(client):
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)
    submitted = submit_authorization(client, owner_headers, asset_id)

    assert submitted.status_code == 201

    reviewer_headers = setup_reviewer(client, role="admin")

    response = decide_authorization(
        client,
        reviewer_headers,
        submitted.json()["id"],
        "approve",
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified"
    assert response.json()["reviewed_by"] is not None

    assets = client.get("/api/v1/assets", headers=owner_headers)
    assert assets.status_code == 200

    asset = next(item for item in assets.json() if item["id"] == asset_id)

    assert asset["authorization_status"] == "verified"
    assert asset["assessment_enabled"] is False

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        audit = db.query(AuditLog).filter(
            AuditLog.action == "asset_authorization.approved",
            AuditLog.target_id == submitted.json()["id"],
        ).first()

        assert audit is not None
    finally:
        db_generator.close()


def test_admin_can_reject_authorization(client):
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)
    submitted = submit_authorization(client, owner_headers, asset_id)

    reviewer_headers = setup_reviewer(client, role="admin")

    response = decide_authorization(
        client,
        reviewer_headers,
        submitted.json()["id"],
        "reject",
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        audit = db.query(AuditLog).filter(
            AuditLog.action == "asset_authorization.rejected",
            AuditLog.target_id == submitted.json()["id"],
        ).first()

        assert audit is not None
    finally:
        db_generator.close()


def test_requester_cannot_approve_own_authorization(client):
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)
    submitted = submit_authorization(client, owner_headers, asset_id)

    response = decide_authorization(
        client,
        owner_headers,
        submitted.json()["id"],
        "approve",
    )

    assert response.status_code == 403


def test_regular_member_cannot_approve_authorization(client):
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)
    submitted = submit_authorization(client, owner_headers, asset_id)

    member_headers = setup_reviewer(client, role="member")

    response = decide_authorization(
        client,
        member_headers,
        submitted.json()["id"],
        "approve",
    )

    assert response.status_code == 403


def test_expired_authorization_cannot_be_approved(client):
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)

    # Submit while the authorization is still valid.
    submitted = submit_authorization(
        client,
        owner_headers,
        asset_id,
    )

    assert submitted.status_code == 201

    # Simulate the authorization expiring after submission.
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        authorization = db.query(AssetAuthorization).filter(
            AssetAuthorization.id == submitted.json()["id"]
        ).first()

        assert authorization is not None

        authorization.expires_at = (
            datetime.now(timezone.utc) - timedelta(days=1)
        )
        db.commit()
    finally:
        db_generator.close()

    reviewer_headers = setup_reviewer(client, role="admin")

    response = decide_authorization(
        client,
        reviewer_headers,
        submitted.json()["id"],
        "approve",
    )

    assert response.status_code == 409
    assert "expired" in response.json()["detail"].lower()



def test_authorization_cannot_be_decided_twice(client):
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)
    submitted = submit_authorization(client, owner_headers, asset_id)

    reviewer_headers = setup_reviewer(client, role="admin")
    authorization_id = submitted.json()["id"]

    first = decide_authorization(
        client,
        reviewer_headers,
        authorization_id,
        "approve",
    )

    second = decide_authorization(
        client,
        reviewer_headers,
        authorization_id,
        "reject",
    )

    assert first.status_code == 200
    assert second.status_code == 409

def test_submit_authorization_request(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    response = submit_authorization(
        client,
        headers,
        asset_id,
    )

    assert response.status_code == 201

    data = response.json()

    assert data["asset_id"] == asset_id
    assert data["status"] == "pending"
    assert data["evidence_type"] == "authorization_letter"
    assert data["scope"]["domains"] == ["example.test"]
    assert data["scope"]["ip_addresses"] == ["192.0.2.10"]
    assert data["reviewed_by"] is None


def test_authorization_request_requires_authentication(client):
    response = client.post(
        "/api/v1/assets/unknown/authorizations",
        json=valid_authorization_payload(),
    )

    assert response.status_code == 401


def test_authorization_request_rejects_unknown_asset(client):
    headers = setup_account(client)

    response = submit_authorization(
        client,
        headers,
        "unknown-asset-id",
    )

    assert response.status_code == 404


def test_authorization_request_rejects_wildcard_domain(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    payload = valid_authorization_payload()
    payload["scope"]["domains"] = ["*.example.test"]

    response = submit_authorization(
        client,
        headers,
        asset_id,
        payload,
    )

    assert response.status_code == 422


def test_authorization_request_rejects_invalid_ip(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    payload = valid_authorization_payload()
    payload["scope"]["ip_addresses"] = ["999.999.999.999"]

    response = submit_authorization(
        client,
        headers,
        asset_id,
        payload,
    )

    assert response.status_code == 422


def test_authorization_request_rejects_invalid_dates(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    payload = valid_authorization_payload()
    payload["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat()

    response = submit_authorization(
        client,
        headers,
        asset_id,
        payload,
    )

    assert response.status_code == 422


def test_authorization_request_rejects_duplicate_pending_request(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    first = submit_authorization(client, headers, asset_id)
    second = submit_authorization(client, headers, asset_id)

    assert first.status_code == 201
    assert second.status_code == 409


def test_submission_does_not_enable_assessment(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    response = submit_authorization(
        client,
        headers,
        asset_id,
    )

    assert response.status_code == 201

    assets_response = client.get(
        "/api/v1/assets",
        headers=headers,
    )

    assert assets_response.status_code == 200

    asset = next(
        item for item in assets_response.json()
        if item["id"] == asset_id
    )

    assert asset["authorization_status"] == "declared"
    assert asset["assessment_enabled"] is False


def test_submission_creates_audit_record(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    response = submit_authorization(
        client,
        headers,
        asset_id,
    )

    assert response.status_code == 201

    # Verify the persisted audit record through the test database.
    # The endpoint response alone does not prove audit persistence.
    from app.database.session import get_db

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "asset_authorization.submitted",
                AuditLog.target_id == response.json()["id"],
            )
            .first()
        )

        assert audit is not None
        assert audit.target_type == "asset_authorization"
    finally:
        db_generator.close()


def test_submission_rejects_empty_scope(client):
    headers = setup_account(client)
    asset_id = setup_asset(client, headers)

    payload = valid_authorization_payload()
    payload["scope"]["domains"] = []
    payload["scope"]["ip_addresses"] = []

    response = submit_authorization(
        client,
        headers,
        asset_id,
        payload,
    )

    assert response.status_code == 422


def lifecycle_request(client, headers, authorization_id, action, reason=None):
    if reason is None:
        reason = f"Lifecycle test: {action} authorization."

    return client.post(
        f"/api/v1/assets/authorizations/{authorization_id}/{action}",
        headers=headers,
        json={"reason": reason},
    )


def create_verified_authorization(client):
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)

    submitted = submit_authorization(client, owner_headers, asset_id)
    assert submitted.status_code == 201, submitted.text

    reviewer_headers = setup_reviewer(client, role="admin")

    approved = decide_authorization(
        client,
        reviewer_headers,
        submitted.json()["id"],
        "approve",
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "verified"

    return owner_headers, reviewer_headers, asset_id, submitted.json()["id"]


def test_lifecycle_suspend_verified_authorization(client):
    owner_headers, reviewer_headers, asset_id, authorization_id = (
        create_verified_authorization(client)
    )

    response = lifecycle_request(
        client, reviewer_headers, authorization_id, "suspend"
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "suspended"

    assets = client.get("/api/v1/assets", headers=owner_headers)
    assert assets.status_code == 200

    asset = next(item for item in assets.json() if item["id"] == asset_id)
    assert asset["authorization_status"] == "suspended"
    assert asset["assessment_enabled"] is False

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        event = db.query(AuthorizationLifecycleEvent).filter(
            AuthorizationLifecycleEvent.authorization_id == authorization_id,
            AuthorizationLifecycleEvent.event_type == "suspended",
        ).first()

        audit = db.query(AuditLog).filter(
            AuditLog.target_id == authorization_id,
            AuditLog.action == "asset_authorization.suspended",
        ).first()

        assert event is not None
        assert event.reason
        assert audit is not None
    finally:
        db_generator.close()


def test_lifecycle_reactivate_suspended_authorization(client):
    owner_headers, reviewer_headers, asset_id, authorization_id = (
        create_verified_authorization(client)
    )

    suspended = lifecycle_request(
        client, reviewer_headers, authorization_id, "suspend"
    )
    assert suspended.status_code == 200, suspended.text

    reactivated = lifecycle_request(
        client, reviewer_headers, authorization_id, "reactivate"
    )

    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "verified"

    assets = client.get("/api/v1/assets", headers=owner_headers)
    asset = next(item for item in assets.json() if item["id"] == asset_id)

    assert asset["authorization_status"] == "verified"
    assert asset["assessment_enabled"] is False


def test_original_requester_cannot_reactivate_authorization(client):
    owner_headers, reviewer_headers, asset_id, authorization_id = (
        create_verified_authorization(client)
    )

    suspended = lifecycle_request(
        client, reviewer_headers, authorization_id, "suspend"
    )
    assert suspended.status_code == 200, suspended.text

    response = lifecycle_request(
        client, owner_headers, authorization_id, "reactivate"
    )

    assert response.status_code == 403


def test_lifecycle_revoke_suspended_authorization(client):
    owner_headers, reviewer_headers, asset_id, authorization_id = (
        create_verified_authorization(client)
    )

    suspended = lifecycle_request(
        client, reviewer_headers, authorization_id, "suspend"
    )
    assert suspended.status_code == 200, suspended.text

    revoked = lifecycle_request(
        client, reviewer_headers, authorization_id, "revoke"
    )

    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    assets = client.get("/api/v1/assets", headers=owner_headers)
    asset = next(item for item in assets.json() if item["id"] == asset_id)

    assert asset["authorization_status"] == "revoked"
    assert asset["assessment_enabled"] is False

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        event = db.query(AuthorizationLifecycleEvent).filter(
            AuthorizationLifecycleEvent.authorization_id == authorization_id,
            AuthorizationLifecycleEvent.event_type == "revoked",
        ).first()

        audit = db.query(AuditLog).filter(
            AuditLog.target_id == authorization_id,
            AuditLog.action == "asset_authorization.revoked",
        ).first()

        assert event is not None
        assert audit is not None
    finally:
        db_generator.close()


def test_pending_authorization_cannot_be_suspended_reactivated_or_revoked(client):
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)
    submitted = submit_authorization(client, owner_headers, asset_id)

    assert submitted.status_code == 201
    authorization_id = submitted.json()["id"]

    reviewer_headers = setup_reviewer(client, role="admin")

    for action in ("suspend", "reactivate", "revoke"):
        response = lifecycle_request(
            client, reviewer_headers, authorization_id, action
        )
        assert response.status_code == 409, (
            f"{action} should reject a pending authorization: {response.text}"
        )


def test_lifecycle_history_is_append_only(client):
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)
    submitted = submit_authorization(client, owner_headers, asset_id)

    assert submitted.status_code == 201
    authorization_id = submitted.json()["id"]

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        event = db.query(AuthorizationLifecycleEvent).filter(
            AuthorizationLifecycleEvent.authorization_id == authorization_id,
            AuthorizationLifecycleEvent.event_type == "submitted",
        ).first()

        assert event is not None
        event_id = event.id

        from sqlalchemy.exc import IntegrityError

        event.reason = "Attempted modification of historical event."

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

        with pytest.raises(IntegrityError):
            db.query(AuthorizationLifecycleEvent).filter(
                AuthorizationLifecycleEvent.id == event_id
            ).delete(synchronize_session=False)
            db.commit()

        db.rollback()

        preserved = db.query(AuthorizationLifecycleEvent).filter(
            AuthorizationLifecycleEvent.id == event_id
        ).first()

        assert preserved is not None
        assert preserved.reason == "Authorization request submitted."
    finally:
        db_generator.close()


def test_reactivation_writes_lifecycle_event_and_audit_record(client):
    owner_headers, reviewer_headers, asset_id, authorization_id = (
        create_verified_authorization(client)
    )

    suspended = lifecycle_request(
        client, reviewer_headers, authorization_id, "suspend"
    )
    assert suspended.status_code == 200, suspended.text

    reason = "Reactivation audit verification."
    reactivated = lifecycle_request(
        client,
        reviewer_headers,
        authorization_id,
        "reactivate",
        reason=reason,
    )

    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "verified"

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        event = db.query(AuthorizationLifecycleEvent).filter(
            AuthorizationLifecycleEvent.authorization_id == authorization_id,
            AuthorizationLifecycleEvent.event_type == "reactivated",
        ).first()

        audit = db.query(AuditLog).filter(
            AuditLog.target_id == authorization_id,
            AuditLog.action == "asset_authorization.reactivated",
        ).first()

        assert event is not None
        assert audit is not None

        assert event.actor_id is not None
        assert event.organization_id is not None
        assert event.reason == reason
        assert event.details["previous_status"] == "suspended"
        assert event.details["new_status"] == "verified"

        assert audit.user_id == event.actor_id
        assert audit.organization_id == event.organization_id
        assert audit.target_type == "asset_authorization"
        assert audit.details["previous_status"] == "suspended"
        assert audit.details["new_status"] == "verified"
        assert audit.details["reason"] == reason
        assert audit.details["assessment_enabled"] is False
    finally:
        db_generator.close()


def test_other_organization_cannot_change_asset_authorization_lifecycle(client):
    owner_headers, reviewer_headers, asset_id, authorization_id = (
        create_verified_authorization(client)
    )

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "other-organization@example.com",
            "password": "StrongPassphrase123!",
            "organization_name": "Separate Security Test Organization",
        },
    )
    assert registration.status_code == 201, registration.text

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "other-organization@example.com",
            "password": "StrongPassphrase123!",
        },
    )
    assert login.status_code == 200, login.text

    other_organization_headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }

    for action in ("suspend", "reactivate", "revoke"):
        response = lifecycle_request(
            client,
            other_organization_headers,
            authorization_id,
            action,
        )
        assert response.status_code == 404, (
            f"{action} should be hidden from another organization. "
            f"Received {response.status_code}: {response.text}"
        )

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        authorization = db.query(AssetAuthorization).filter(
            AssetAuthorization.id == authorization_id
        ).first()

        assert authorization is not None
        assert authorization.status == "verified"

        forbidden_events = db.query(AuthorizationLifecycleEvent).filter(
            AuthorizationLifecycleEvent.authorization_id == authorization_id,
            AuthorizationLifecycleEvent.event_type.in_(
                ("suspended", "reactivated", "revoked")
            ),
        ).count()

        forbidden_audits = db.query(AuditLog).filter(
            AuditLog.target_id == authorization_id,
            AuditLog.action.in_(
                (
                    "asset_authorization.suspended",
                    "asset_authorization.reactivated",
                    "asset_authorization.revoked",
                )
            ),
        ).count()

        assert forbidden_events == 0
        assert forbidden_audits == 0
    finally:
        db_generator.close()
