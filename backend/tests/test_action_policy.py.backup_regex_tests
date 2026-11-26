from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.action_engine.policy import evaluate_action_policy


def make_objects():
    now = datetime.now(timezone.utc)

    asset = SimpleNamespace(
        id="asset-001",
        organization_id="org-001",
        identifier="execution-server.local",
        authorization_status="verified",
        assessment_enabled=True,
    )

    action = SimpleNamespace(
        id="action-001",
        organization_id="org-001",
        target_type="asset",
        target_id="asset-001",
        action_type="collect_inventory",
        status="approved",
    )

    approval = SimpleNamespace(decision="approve")

    authorization = SimpleNamespace(
        id="authorization-001",
        organization_id="org-001",
        asset_id="asset-001",
        status="verified",
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=30),
        scope={
            "domains": ["execution-server.local"],
            "ip_addresses": [],
            "excluded_targets": [],
            "allowed_assessment_types": ["collect_inventory"],
        },
    )

    return action, asset, approval, authorization


def evaluate(action, asset, approval, authorization, **kwargs):
    return evaluate_action_policy(
        action, asset, approval, authorization, **kwargs
    )


def test_valid_action_passes_policy():
    action, asset, approval, authorization = make_objects()
    assert evaluate(action, asset, approval, authorization).allowed is True


def test_emergency_stop_blocks_action():
    action, asset, approval, authorization = make_objects()
    result = evaluate(
        action, asset, approval, authorization, emergency_stop=True
    )
    assert not result.allowed
    assert "Emergency stop" in result.reason


def test_missing_authorization_is_blocked():
    action, asset, approval, _ = make_objects()
    result = evaluate(action, asset, approval, None)
    assert not result.allowed
    assert "authorization record" in result.reason


def test_wrong_authorization_organization_is_blocked():
    action, asset, approval, authorization = make_objects()
    authorization.organization_id = "other-org"
    assert not evaluate(action, asset, approval, authorization).allowed


def test_wrong_authorization_asset_is_blocked():
    action, asset, approval, authorization = make_objects()
    authorization.asset_id = "other-asset"
    assert not evaluate(action, asset, approval, authorization).allowed


def test_non_verified_authorization_is_blocked():
    action, asset, approval, authorization = make_objects()
    authorization.status = "suspended"
    assert not evaluate(action, asset, approval, authorization).allowed


def test_expired_authorization_is_blocked():
    action, asset, approval, authorization = make_objects()
    authorization.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    result = evaluate(action, asset, approval, authorization)
    assert not result.allowed
    assert "expired" in result.reason


def test_future_authorization_is_blocked():
    action, asset, approval, authorization = make_objects()
    authorization.valid_from = datetime.now(timezone.utc) + timedelta(days=1)
    result = evaluate(action, asset, approval, authorization)
    assert not result.allowed
    assert "not valid yet" in result.reason


def test_disabled_assessment_is_blocked():
    action, asset, approval, authorization = make_objects()
    asset.assessment_enabled = False
    assert not evaluate(action, asset, approval, authorization).allowed


def test_missing_approval_is_blocked():
    action, asset, _, authorization = make_objects()
    assert not evaluate(action, asset, None, authorization).allowed


def test_rejected_approval_is_blocked():
    action, asset, approval, authorization = make_objects()
    approval.decision = "reject"
    assert not evaluate(action, asset, approval, authorization).allowed


def test_cross_organization_asset_is_blocked():
    action, asset, approval, authorization = make_objects()
    asset.organization_id = "different-org"
    assert not evaluate(action, asset, approval, authorization).allowed


def test_unsupported_action_is_blocked():
    action, asset, approval, authorization = make_objects()
    action.action_type = "isolate_endpoint"
    result = evaluate(action, asset, approval, authorization)
    assert not result.allowed
    assert "handler" in result.reason


def test_action_type_must_be_in_authorization_scope():
    action, asset, approval, authorization = make_objects()
    authorization.scope["allowed_assessment_types"] = ["review_configuration"]
    result = evaluate(action, asset, approval, authorization)
    assert not result.allowed
    assert "assessment type" in result.reason


def test_excluded_target_overrides_allowed_target():
    action, asset, approval, authorization = make_objects()
    authorization.scope["excluded_targets"] = ["EXECUTION-SERVER.LOCAL."]
    result = evaluate(action, asset, approval, authorization)
    assert not result.allowed
    assert "excluded" in result.reason


def test_subdomain_is_not_implicitly_authorized():
    action, asset, approval, authorization = make_objects()
    asset.identifier = "api.execution-server.local"
    result = evaluate(action, asset, approval, authorization)
    assert not result.allowed
    assert "not explicitly included" in result.reason


def test_asset_cache_status_does_not_grant_authorization():
    action, asset, approval, authorization = make_objects()
    asset.authorization_status = "declared"
    assert evaluate(action, asset, approval, authorization).allowed


def test_malformed_scope_is_blocked():
    action, asset, approval, authorization = make_objects()
    authorization.scope = {"domains": "execution-server.local"}
    assert not evaluate(action, asset, approval, authorization).allowed


def test_non_asset_target_type_is_blocked():
    action, asset, approval, authorization = make_objects()
    action.target_type = "network"
    assert not evaluate(action, asset, approval, authorization).allowed


def test_pending_action_is_blocked():
    action, asset, approval, authorization = make_objects()
    action.status = "pending_approval"
    assert not evaluate(action, asset, approval, authorization).allowed
