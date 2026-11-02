from app.models import ExecutionRecord
from app.action_engine.policy import evaluate_action_policy


def enqueue_action(
    db,
    action,
    asset,
    approval,
    emergency_stop=False,
    authorization=None,
):
    """
    Create a queued execution record after policy validation.

    This function does NOT execute the action.
    """

    decision = evaluate_action_policy(
        action=action,
        asset=asset,
        approval=approval,
        authorization=authorization,
        emergency_stop=emergency_stop,
    )

    if not decision.allowed:
        raise ValueError(decision.reason)

    existing = (
        db.query(ExecutionRecord)
        .filter(ExecutionRecord.action_request_id == action.id)
        .first()
    )

    if existing is not None:
        return existing

    record = ExecutionRecord(
        action_request_id=action.id,
        organization_id=action.organization_id,
        status="queued",
        result={
            "mode": "queued_only",
            "execution_started": False,
            "message": "Action queued. No security operation has been executed.",
        },
        verified=False,
    )

    db.add(record)
    db.flush()

    return record
