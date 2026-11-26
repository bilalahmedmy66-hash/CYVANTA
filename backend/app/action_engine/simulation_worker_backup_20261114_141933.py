"""Manually invoked, simulation-only worker for CYVANTA."""

from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.models import (
    EmergencyStopState,
    ExecutionRecord,
    SimulationDispatch,
    SimulationDispatchEvent,
)
from app.action_engine.worker_registry import WorkerNotEligibleError
from app.action_engine.platform_emergency_stop import (
    is_platform_emergency_stop_active,
    PlatformEmergencyStopStateUnavailable,
)


class SimulationWorkerError(RuntimeError):
    """Raised when simulation processing cannot safely proceed."""


def _reject(message: str) -> None:
    raise SimulationWorkerError(message)


def _require_safe_organization_stop(db, organization_id: str) -> None:
    try:
        states = (
            db.query(EmergencyStopState)
            .filter(
                EmergencyStopState.organization_id == organization_id
            )
            .all()
        )
    except SQLAlchemyError as exc:
        raise SimulationWorkerError(
            "Organization emergency-stop state is unavailable."
        ) from exc

    if len(states) != 1:
        _reject("Exactly one organization emergency-stop record is required.")

    if states[0].is_active is not False:
        _reject("Organization emergency stop is active or invalid.")


def _build_synthetic_inventory() -> dict:
    return {
        "mode": "simulation_only",
        "action_type": "collect_inventory",
        "source": "synthetic_fixture",
        "inventory": {
            "asset_count": 1,
            "assets": [
                {
                    "asset_id": "synthetic-asset-001",
                    "asset_type": "synthetic",
                    "identifier": "demo.example.test",
                    "status": "simulated",
                }
            ],
        },
        "execution_started": False,
        "external_side_effects": False,
    }


def process_simulation_dispatch(
    db,
    dispatch_id: str,
    worker_registry,
    worker_id: str,
) -> SimulationDispatch:
    """Process one claimed dispatch using synthetic data only."""

    if db.in_transaction():
        _reject("A clean database session is required.")

    if not isinstance(dispatch_id, str) or not dispatch_id.strip():
        _reject("A valid simulation dispatch ID is required.")

    if not isinstance(worker_id, str) or not worker_id.strip():
        _reject("A valid worker ID is required.")

    try:
        if db.get_bind().dialect.name != "sqlite":
            _reject("Simulation processing is supported only on SQLite.")

        try:
            worker = worker_registry.require_eligible(worker_id.strip())
        except WorkerNotEligibleError as exc:
            raise SimulationWorkerError(
                "Worker is not eligible for simulation."
            ) from exc

        if (
            worker.worker_type != "simulation"
            or "simulation" not in worker.capabilities
        ):
            _reject("Only eligible simulation workers are permitted.")

        connection = db.connection()
        connection.exec_driver_sql("BEGIN IMMEDIATE")

        dispatch = (
            db.query(SimulationDispatch)
            .filter(SimulationDispatch.id == dispatch_id.strip())
            .one_or_none()
        )

        if dispatch is None:
            _reject("Simulation dispatch was not found.")

        if dispatch.status != "claimed":
            _reject("Only claimed dispatches can be processed.")

        if dispatch.worker_id != worker.worker_id:
            _reject("Dispatch is assigned to a different worker.")

        execution = (
            db.query(ExecutionRecord)
            .filter(
                ExecutionRecord.id == dispatch.execution_record_id,
                ExecutionRecord.organization_id == dispatch.organization_id,
            )
            .one_or_none()
        )

        if execution is None:
            _reject("Associated execution record was not found.")

        if execution.status != "queued":
            _reject("Associated execution record must remain queued.")

        try:
            if is_platform_emergency_stop_active(db):
                _reject("Platform emergency stop is active.")
        except PlatformEmergencyStopStateUnavailable as exc:
            raise SimulationWorkerError(
                "Platform emergency-stop state is unavailable."
            ) from exc

        _require_safe_organization_stop(db, dispatch.organization_id)

        result = _build_synthetic_inventory()
        now = datetime.now(timezone.utc)

        dispatch.status = "completed"
        dispatch.completed_at = now
        dispatch.synthetic_result = result

        db.add(
            SimulationDispatchEvent(
                dispatch_id=dispatch.id,
                organization_id=dispatch.organization_id,
                event_type="simulation_completed",
                worker_id=worker.worker_id,
                details={
                    "mode": "simulation_only",
                    "source": "synthetic_fixture",
                    "execution_started": False,
                    "external_side_effects": False,
                    "synthetic_asset_count": 1,
                },
            )
        )

        db.flush()
        db.commit()
        db.refresh(dispatch)

        return dispatch

    except Exception as exc:
        db.rollback()

        if isinstance(exc, SimulationWorkerError):
            raise

        if isinstance(exc, SQLAlchemyError):
            raise SimulationWorkerError(
                "Simulation processing failed safely."
            ) from exc

        raise
