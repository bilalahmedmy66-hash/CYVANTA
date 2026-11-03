from datetime import datetime, timezone

from sqlalchemy import update

from app.models import ExecutionRecord


ALLOWED_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


TERMINAL_STATES = {"completed", "failed", "cancelled"}


def transition_execution(db, execution_id: str, target_status: str):
    """
    Safely transition an execution record between permitted states.

    This function updates lifecycle state only. It does not execute
    security operations or start an execution worker.
    """

    if target_status not in ALLOWED_TRANSITIONS:
        raise ValueError(f"Unsupported execution status: {target_status}")

    record = (
        db.query(ExecutionRecord)
        .filter(ExecutionRecord.id == execution_id)
        .first()
    )

    if record is None:
        raise ValueError("Execution record not found.")

    current_status = record.status

    allowed_targets = ALLOWED_TRANSITIONS.get(current_status)

    if allowed_targets is None or target_status not in allowed_targets:
        raise ValueError(
            f"Invalid execution transition: {current_status} -> {target_status}"
        )

    now = datetime.now(timezone.utc)

    values = {"status": target_status}

    if target_status == "running":
        values["started_at"] = now

    if target_status in TERMINAL_STATES:
        values["completed_at"] = now

    result = db.execute(
        update(ExecutionRecord)
        .where(
            ExecutionRecord.id == execution_id,
            ExecutionRecord.status == current_status,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        raise ValueError(
            "Execution state changed concurrently. Reload and retry."
        )

    db.flush()
    db.refresh(record)

    return record
