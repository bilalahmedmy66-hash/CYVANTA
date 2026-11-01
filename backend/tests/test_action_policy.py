from types import SimpleNamespace

from app.action_engine.policy import evaluate_action_policy


def make_objects():
    asset = SimpleNamespace(
        id="asset-001",
        organization_id="org-001",
        authorization_status="verified",
        assessment_enabled=True,
    )

    action = SimpleNamespace(
        id="action-001",
        organization_id="org-001",
        target_id="asset-001",
        action_type="collect_inventory",
        status="approved",
    )

    approval = SimpleNamespace(
        decision="approve",
    )

    return action, asset, approval


def test_valid_action_passes_policy():
    action, asset, approval = make_objects()
    result = evaluate_action_policy(action, asset, approval)
    assert result.allowed is True


def test_emergency_stop_blocks_action():
    action, asset, approval = make_objects()
    result = evaluate_action_policy(
        action, asset, approval, emergency_stop=True
    )
    assert result.allowed is False
    assert "Emergency stop" in result.reason


def test_unverified_asset_is_blocked():
    action, asset, approval = make_objects()
    asset.authorization_status = "declared"
    result = evaluate_action_policy(action, asset, approval)
    assert result.allowed is False


def test_disabled_assessment_is_blocked():
    action, asset, approval = make_objects()
    asset.assessment_enabled = False
    result = evaluate_action_policy(action, asset, approval)
    assert result.allowed is False


def test_missing_approval_is_blocked():
    action, asset, _ = make_objects()
    result = evaluate_action_policy(action, asset, None)
    assert result.allowed is False


def test_rejected_approval_is_blocked():
    action, asset, approval = make_objects()
    approval.decision = "reject"
    result = evaluate_action_policy(action, asset, approval)
    assert result.allowed is False


def test_cross_organization_asset_is_blocked():
    action, asset, approval = make_objects()
    asset.organization_id = "different-org"
    result = evaluate_action_policy(action, asset, approval)
    assert result.allowed is False


def test_unsupported_action_is_blocked():
    action, asset, approval = make_objects()
    action.action_type = "isolate_endpoint"
    result = evaluate_action_policy(action, asset, approval)
    assert result.allowed is False
    assert "execution handler" in result.reason


def test_pending_action_is_blocked():
    action, asset, approval = make_objects()
    action.status = "pending_approval"
    result = evaluate_action_policy(action, asset, approval)
    assert result.allowed is False
