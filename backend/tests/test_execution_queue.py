from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.action_engine.execution_queue import enqueue_action


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

    approval = SimpleNamespace(decision="approve")

    return action, asset, approval


def make_db(existing=None):
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.first.return_value = existing
    return db


def test_valid_action_is_queued_without_execution():
    action, asset, approval = make_objects()
    db = make_db()

    record = enqueue_action(db, action, asset, approval)

    assert record.status == "queued"
    assert record.verified is False
    assert record.result["execution_started"] is False
    assert record.result["mode"] == "queued_only"
    db.add.assert_called_once()
    db.flush.assert_called_once()


def test_unverified_asset_cannot_be_queued():
    action, asset, approval = make_objects()
    asset.authorization_status = "declared"
    db = make_db()

    with pytest.raises(ValueError, match="authorization"):
        enqueue_action(db, action, asset, approval)

    db.add.assert_not_called()


def test_missing_approval_cannot_be_queued():
    action, asset, _ = make_objects()
    db = make_db()

    with pytest.raises(ValueError, match="approval"):
        enqueue_action(db, action, asset, None)

    db.add.assert_not_called()


def test_emergency_stop_blocks_queue():
    action, asset, approval = make_objects()
    db = make_db()

    with pytest.raises(ValueError, match="Emergency stop"):
        enqueue_action(
            db, action, asset, approval, emergency_stop=True
        )

    db.add.assert_not_called()


def test_unsupported_action_cannot_be_queued():
    action, asset, approval = make_objects()
    action.action_type = "isolate_endpoint"
    db = make_db()

    with pytest.raises(ValueError, match="execution handler"):
        enqueue_action(db, action, asset, approval)

    db.add.assert_not_called()


def test_existing_queue_record_is_returned():
    action, asset, approval = make_objects()
    existing = SimpleNamespace(
        id="execution-001",
        status="queued",
    )
    db = make_db(existing=existing)

    record = enqueue_action(db, action, asset, approval)

    assert record is existing
    db.add.assert_not_called()
    db.flush.assert_not_called()


def test_cross_organization_target_is_blocked():
    action, asset, approval = make_objects()
    asset.organization_id = "other-org"
    db = make_db()

    with pytest.raises(ValueError, match="organization"):
        enqueue_action(db, action, asset, approval)

    db.add.assert_not_called()
