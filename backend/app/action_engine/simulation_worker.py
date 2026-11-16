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
from app.action_engine.simulation_dispatcher import (
    SimulationDispatchValidationError,
    validate_simulation_dispatch,
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

        # Acquire the database write lock before the registry lock.
        connection = db.connection()
        connection.exec_driver_sql("BEGIN IMMEDIATE")

        # Hold worker eligibility until the transaction has committed.
        with worker_registry.eligible_worker(worker_id.strip()) as worker:
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

            # Revalidate all current authorization and safety conditions.
            try:
                validation = validate_simulation_dispatch(
                    db=db,
                    execution_record_id=dispatch.execution_record_id,
                    worker_registry=worker_registry,
                    worker_id=worker.worker_id,
                )
            except SimulationDispatchValidationError as exc:
                raise SimulationWorkerError(
                    "Dispatch failed fresh safety validation."
                ) from exc

            if (
                validation.execution_record_id != dispatch.execution_record_id
                or validation.organization_id != dispatch.organization_id
                or validation.worker_id != dispatch.worker_id
                or validation.worker_id != worker.worker_id
            ):
                _reject("Fresh validation does not match the claimed dispatch.")

            # This is synthetic fixture data only. No operation is executed.
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

        if isinstance(exc, (WorkerNotEligibleError, SimulationDispatchValidationError)):
            raise SimulationWorkerError(
                "Worker eligibility or fresh safety validation failed."
            ) from exc

        if isinstance(exc, SQLAlchemyError):
            raise SimulationWorkerError(
                "Simulation processing failed safely."
            ) from exc

        raise
