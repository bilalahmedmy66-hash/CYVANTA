import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from datetime import datetime, timedelta, timezone

from app.models import Asset, AssetAuthorization, AuditLog, Membership, ExecutionRecord


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

        now = datetime.now(timezone.utc)

        authorization = AssetAuthorization(
            organization_id=asset.organization_id,
            asset_id=asset.id,
            status="verified",
            submitted_by=asset.created_by,
            reviewed_by=asset.created_by,
            evidence_type="authorization_letter",
            evidence_reference="TEST-EVIDENCE-REFERENCE",
            scope={
                "domains": [asset.identifier],
                "ip_addresses": [],
                "excluded_targets": [],
                "allowed_assessment_types": ["collect_inventory"],
            },
            valid_from=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=30),
            reviewed_at=now,
        )

        asset.authorization_status = "verified"
        asset.assessment_enabled = True
        db.add(authorization)
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
    session_factory = api_context["session_factory"]

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

    with session_factory() as db:
        queue_audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "execution.queued",
                AuditLog.target_id == first.json()["id"],
            )
            .all()
        )

        assert len(queue_audits) == 1

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

def add_second_organization(session_factory, first_email):
    from app.models import User, Organization, Membership

    with session_factory() as db:
        first_user = db.query(User).filter(
            User.email == first_email
        ).first()
        second_user = db.query(User).filter(
            User.email == "other-organization@example.com"
        ).first()

        assert first_user is not None
        assert second_user is not None

        second_membership = db.query(Membership).filter(
            Membership.user_id == second_user.id
        ).first()
        assert second_membership is not None

        first_membership = db.query(Membership).filter(
            Membership.user_id == first_user.id
        ).first()
        assert first_membership is not None

        second_org_id = second_membership.organization_id
        first_org_id = first_membership.organization_id

        db.add(
            Membership(
                user_id=first_user.id,
                organization_id=second_org_id,
                role="member",
            )
        )
        db.commit()

        return first_org_id, second_org_id


def test_multiple_organizations_require_explicit_header(api_context):
    client = api_context["client"]

    first_headers = setup_account(client)
    setup_account(
        client,
        email="other-organization@example.com",
    )

    add_second_organization(
        api_context["session_factory"],
        "execution@example.com",
    )

    response = client.get(
        "/api/v1/executions",
        headers=first_headers,
    )

    assert response.status_code == 400
    assert "X-Organization-ID" in response.json()["detail"]


def test_valid_organization_header_is_accepted(api_context):
    client = api_context["client"]

    first_headers = setup_account(client)
    setup_account(
        client,
        email="other-organization@example.com",
    )

    first_org_id, second_org_id = add_second_organization(
        api_context["session_factory"],
        "execution@example.com",
    )

    headers_first = {
        **first_headers,
        "X-Organization-ID": first_org_id,
    }
    headers_second = {
        **first_headers,
        "X-Organization-ID": second_org_id,
    }

    first_response = client.get(
        "/api/v1/executions",
        headers=headers_first,
    )
    second_response = client.get(
        "/api/v1/executions",
        headers=headers_second,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200


def test_invalid_organization_header_is_rejected(api_context):
    client = api_context["client"]

    first_headers = setup_account(client)
    setup_account(
        client,
        email="other-organization@example.com",
    )

    add_second_organization(
        api_context["session_factory"],
        "execution@example.com",
    )

    invalid_headers = {
        **first_headers,
        "X-Organization-ID": "organization-user-does-not-belong-to",
    }

    response = client.get(
        "/api/v1/executions",
        headers=invalid_headers,
    )

    assert response.status_code == 403


def test_active_emergency_stop_blocks_new_queue_request(api_context):
    client = api_context["client"]

    headers, action_id = prepare_approved_action(api_context)

    activation = client.post(
        "/api/v1/emergency-stop/activate",
        headers=headers,
        json={
            "reason": "Testing execution queue emergency stop."
        },
    )

    assert activation.status_code == 200
    assert activation.json()["is_active"] is True

    response = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )

    assert response.status_code == 409
    assert "Emergency stop is active" in response.json()["detail"]

    listing = client.get(
        "/api/v1/executions",
        headers=headers,
    )

    assert listing.status_code == 200
    assert listing.json() == []


def test_unavailable_emergency_stop_state_blocks_queue(
    api_context,
    monkeypatch,
):
    from app.action_engine.emergency_stop import (
        EmergencyStopStateUnavailable,
    )
    import app.api.executions as execution_api

    client = api_context["client"]

    headers, action_id = prepare_approved_action(api_context)

    def simulate_unavailable_state(*args, **kwargs):
        raise EmergencyStopStateUnavailable(
            "Emergency Stop state could not be verified."
        )

    monkeypatch.setattr(
        execution_api,
        "is_emergency_stop_active",
        simulate_unavailable_state,
    )

    response = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )

    assert response.status_code == 503
    assert (
        "Emergency Stop state could not be verified"
        in response.json()["detail"]
    )

    listing = client.get(
        "/api/v1/executions",
        headers=headers,
    )

    assert listing.status_code == 200
    assert listing.json() == []


def test_real_authorization_api_flow_reaches_queue_only(api_context):
    """Exercise real authorization and action APIs; never execute an operation."""
    from app.models import AuditLog, User

    client = api_context["client"]
    session_factory = api_context["session_factory"]

    # 1. Register the organization owner and an asset through the API.
    owner_headers = setup_account(client)
    asset_id = setup_asset(client, owner_headers)

    # 2. Submit an actual authorization request through the API.
    now = datetime.now(timezone.utc)
    authorization_payload = {
        "evidence_type": "authorization_letter",
        "evidence_reference": "INTEGRATION-TEST-EVIDENCE-001",
        "scope": {
            "domains": ["execution-server.local"],
            "ip_addresses": [],
            "excluded_targets": [],
            "allowed_assessment_types": ["collect_inventory"],
        },
        "valid_from": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
    }

    submitted = client.post(
        f"/api/v1/assets/{asset_id}/authorizations",
        headers=owner_headers,
        json=authorization_payload,
    )
    assert submitted.status_code == 201, submitted.text
    authorization_id = submitted.json()["id"]

    # 3. Create a separate reviewer account and move its membership
    # into the owner's organization using this isolated test database.
    reviewer_registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "execution-reviewer@example.com",
            "password": "StrongPassphrase123!",
            "organization_name": "Temporary Reviewer Organization",
        },
    )
    assert reviewer_registration.status_code == 201, reviewer_registration.text

    reviewer_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "execution-reviewer@example.com",
            "password": "StrongPassphrase123!",
        },
    )
    assert reviewer_login.status_code == 200, reviewer_login.text

    with session_factory() as db:
        owner = db.query(User).filter(
            User.email == "execution@example.com"
        ).first()
        reviewer = db.query(User).filter(
            User.email == "execution-reviewer@example.com"
        ).first()

        assert owner is not None
        assert reviewer is not None

        owner_membership = db.query(Membership).filter(
            Membership.user_id == owner.id
        ).first()
        reviewer_memberships = db.query(Membership).filter(
            Membership.user_id == reviewer.id
        ).all()

        assert owner_membership is not None
        assert len(reviewer_memberships) == 1

        for membership in reviewer_memberships:
            db.delete(membership)

        db.add(
            Membership(
                user_id=reviewer.id,
                organization_id=owner_membership.organization_id,
                role="admin",
            )
        )
        db.commit()

    reviewer_headers = {
        "Authorization": f"Bearer {reviewer_login.json()['access_token']}"
    }

    # 4. The independent admin approves the actual authorization request.
    authorization_decision = client.post(
        f"/api/v1/assets/authorizations/{authorization_id}/decision",
        headers=reviewer_headers,
        json={
            "decision": "approve",
            "reason": "Integration test: authorization evidence reviewed.",
        },
    )
    assert authorization_decision.status_code == 200, authorization_decision.text
    assert authorization_decision.json()["status"] == "verified"

    # Authorization approval must not enable assessments.
    with session_factory() as db:
        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        assert asset is not None
        assert asset.authorization_status == "verified"
        assert asset.assessment_enabled is False

    # 5. Create a mission and propose an action through the real APIs.
    mission_response = client.post(
        "/api/v1/missions",
        headers=owner_headers,
        json={
            "title": "Authorization Integration Test",
            "objective": "Verify the controlled queue integration.",
            "priority": "normal",
            "asset_id": asset_id,
        },
    )
    assert mission_response.status_code == 201, mission_response.text
    mission_id = mission_response.json()["id"]

    proposal = client.post(
        f"/api/v1/missions/{mission_id}/actions",
        headers=owner_headers,
        json={
            "action_type": "collect_inventory",
            "target_id": asset_id,
            "description": "Test-only inventory action proposal.",
        },
    )
    assert proposal.status_code == 201, proposal.text
    action_id = proposal.json()["id"]

    # The separate admin also approves the action.
    action_decision = client.post(
        f"/api/v1/actions/{action_id}/decision",
        headers=reviewer_headers,
        json={
            "decision": "approve",
            "reason": "Integration test: action reviewed.",
        },
    )
    assert action_decision.status_code == 200, action_decision.text

    # 6. Verified authorization alone is insufficient:
    # the independent assessment-enabled gate must still block queueing.
    blocked = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=owner_headers,
    )
    assert blocked.status_code == 409, blocked.text

    execution_listing = client.get(
        "/api/v1/executions",
        headers=owner_headers,
    )
    assert execution_listing.status_code == 200
    assert execution_listing.json() == []

    # Test fixture only: simulate the separate assessment-enable control.
    # This is NOT an application API or a claim that such an API exists.
    with session_factory() as db:
        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        assert asset is not None
        asset.assessment_enabled = True
        db.commit()

    # 7. The action may now enter the queue, but must not execute.
    queued = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=owner_headers,
    )
    assert queued.status_code == 201, queued.text

    execution = queued.json()
    assert execution["action_request_id"] == action_id
    assert execution["status"] == "queued"
    assert execution["verified"] is False
    assert execution["result"]["mode"] == "queued_only"
    assert execution["result"]["execution_started"] is False

    # 8. Verify that the execution audit record references the real
    # authorization approved earlier in this same API workflow.
    with session_factory() as db:
        audit = db.query(AuditLog).filter(
            AuditLog.action == "execution.queued",
            AuditLog.target_id == execution["id"],
        ).first()

        assert audit is not None
        assert audit.details["authorization_id"] == authorization_id
        assert audit.details["execution_started"] is False


def test_admin_can_cancel_queued_execution(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    headers, action_id = prepare_approved_action(api_context)

    queued = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )
    assert queued.status_code == 201

    execution_id = queued.json()["id"]

    response = client.post(
        f"/api/v1/executions/{execution_id}/cancel",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert response.json()["started_at"] is None
    assert response.json()["completed_at"] is not None

    with session_factory() as db:
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "execution.cancelled",
                AuditLog.target_id == execution_id,
            )
            .all()
        )

        assert len(audits) == 1
        assert audits[0].details["previous_status"] == "queued"
        assert audits[0].details["new_status"] == "cancelled"


def test_non_admin_cannot_cancel_execution(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    headers, action_id = prepare_approved_action(api_context)

    queued = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )
    assert queued.status_code == 201

    execution_id = queued.json()["id"]

    with session_factory() as db:
        membership = db.query(Membership).first()
        assert membership is not None
        membership.role = "member"
        db.commit()

    response = client.post(
        f"/api/v1/executions/{execution_id}/cancel",
        headers=headers,
    )

    assert response.status_code == 403

    with session_factory() as db:
        record = db.query(ExecutionRecord).filter(
            ExecutionRecord.id == execution_id
        ).first()

        assert record.status == "queued"


def test_other_organization_cannot_cancel_execution(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    headers_one, action_id = prepare_approved_action(api_context)

    queued = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers_one,
    )
    assert queued.status_code == 201

    execution_id = queued.json()["id"]

    headers_two = setup_account(
        client,
        email="cancel-other-organization@example.com",
    )

    response = client.post(
        f"/api/v1/executions/{execution_id}/cancel",
        headers=headers_two,
    )

    assert response.status_code == 404

    with session_factory() as db:
        record = db.query(ExecutionRecord).filter(
            ExecutionRecord.id == execution_id
        ).first()

        assert record.status == "queued"


def test_running_execution_cannot_be_cancelled(api_context):
    client = api_context["client"]
    session_factory = api_context["session_factory"]

    headers, action_id = prepare_approved_action(api_context)

    queued = client.post(
        f"/api/v1/actions/{action_id}/queue",
        headers=headers,
    )
    assert queued.status_code == 201

    execution_id = queued.json()["id"]

    with session_factory() as db:
        record = db.query(ExecutionRecord).filter(
            ExecutionRecord.id == execution_id
        ).first()

        assert record is not None
        record.status = "running"
        record.started_at = datetime.now(timezone.utc)
        db.commit()

    response = client.post(
        f"/api/v1/executions/{execution_id}/cancel",
        headers=headers,
    )

    assert response.status_code == 409

    with session_factory() as db:
        record = db.query(ExecutionRecord).filter(
            ExecutionRecord.id == execution_id
        ).first()

        assert record.status == "running"
        assert record.completed_at is None
