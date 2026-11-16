from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.models import (
    ActionApproval,
    ActionRequest,
    Asset,
    AssetAuthorization,
    EmergencyStopState,
    ExecutionRecord,
    Mission,
    SimulationDispatch,
    SimulationDispatchEvent,
)
from app.action_engine.policy import evaluate_action_policy
from app.action_engine.worker_registry import WorkerNotEligibleError
from app.action_engine.platform_emergency_stop import (
    is_platform_emergency_stop_active,
    PlatformEmergencyStopStateUnavailable,
)


class SimulationDispatchValidationError(RuntimeError):
    """Raised when a simulation dispatch fails a safety validation."""


@dataclass(frozen=True)
class SimulationDispatchValidation:
    execution_record_id: str
    action_request_id: str
    organization_id: str
    worker_id: str
    action_type: str
    target_id: str
    mode: str = "simulation_only"
    execution_started: bool = False


def _reject(message: str):
    raise SimulationDispatchValidationError(message)


def _require_safe_organization_stop(db, organization_id: str) -> None:
    """
    Dispatcher-specific strict check.

    Exactly one organization stop record must exist and its state
    must be the Boolean value False. Missing, malformed or unreadable
    state is treated as unsafe.
    """
    try:
        states = (
            db.query(EmergencyStopState)
            .filter(
                EmergencyStopState.organization_id == organization_id
            )
            .all()
        )
    except SQLAlchemyError as exc:
        raise SimulationDispatchValidationError(
            "Organization emergency-stop state is unavailable."
        ) from exc

    if len(states) != 1:
        _reject(
            "Dispatch blocked: exactly one organization emergency-stop "
            "record is required."
        )

    if states[0].is_active is not False:
        _reject(
            "Dispatch blocked: organization emergency stop is active "
            "or its state is invalid."
        )


def validate_simulation_dispatch(
    db,
    execution_record_id: str,
    worker_registry,
    worker_id: str,
) -> SimulationDispatchValidation:
    """
    Validate a queued execution for simulation-only dispatch.

    This function is validation-only:
    - It does not create or claim a SimulationDispatch.
    - It does not change ExecutionRecord.
    - It does not start or execute any operation.
    - It does not access the network or shell.
    """

    if not isinstance(execution_record_id, str) or not execution_record_id.strip():
        _reject("A valid execution record ID is required.")

    if not isinstance(worker_id, str) or not worker_id.strip():
        _reject("A valid worker ID is required.")

    # Require an explicitly activated simulation worker.
    try:
        worker = worker_registry.require_eligible(worker_id.strip())
    except WorkerNotEligibleError as exc:
        raise SimulationDispatchValidationError(
            "Dispatch blocked: worker is not eligible."
        ) from exc

    if worker.worker_type != "simulation":
        _reject("Only simulation workers are permitted.")

    if "simulation" not in worker.capabilities:
        _reject("Worker does not have the simulation capability.")

    # Load the execution record.
    try:
        execution = (
            db.query(ExecutionRecord)
            .filter(ExecutionRecord.id == execution_record_id.strip())
            .one_or_none()
        )
    except SQLAlchemyError as exc:
        raise SimulationDispatchValidationError(
            "Execution record could not be safely loaded."
        ) from exc

    if execution is None:
        _reject("Execution record was not found.")

    if execution.status != "queued":
        _reject("Only queued execution records can be considered.")

    organization_id = execution.organization_id

    # Platform emergency stop must be explicitly safe.
    try:
        if is_platform_emergency_stop_active(db):
            _reject("Dispatch blocked by the platform emergency stop.")
    except PlatformEmergencyStopStateUnavailable as exc:
        raise SimulationDispatchValidationError(
            "Platform emergency-stop state is unavailable."
        ) from exc

    # Organization stop must have an existing, explicitly inactive row.
    _require_safe_organization_stop(db, organization_id)

    # Load and validate the action request.
    try:
        action = (
            db.query(ActionRequest)
            .filter(ActionRequest.id == execution.action_request_id)
            .one_or_none()
        )
    except SQLAlchemyError as exc:
        raise SimulationDispatchValidationError(
            "Action request could not be safely loaded."
        ) from exc

    if action is None:
        _reject("Associated action request was not found.")

    if action.organization_id != organization_id:
        _reject("Execution and action organization do not match.")

    if action.status != "approved":
        _reject("Action request is not approved.")

    if action.action_type != "collect_inventory":
        _reject("Action type is outside the permitted simulation scope.")

    if action.target_type != "asset" or not action.target_id:
        _reject("Only asset-targeted simulation requests are permitted.")

    # Verify the approval belongs to this exact action and organization.
    try:
        approvals = (
            db.query(ActionApproval)
            .filter(ActionApproval.action_request_id == action.id)
            .all()
        )
    except SQLAlchemyError as exc:
        raise SimulationDispatchValidationError(
            "Action approval could not be safely loaded."
        ) from exc

    if len(approvals) != 1:
        _reject("Exactly one matching action approval is required.")

    approval = approvals[0]

    if approval.action_request_id != action.id:
        _reject("Approval action association is invalid.")

    if approval.organization_id != organization_id:
        _reject("Approval organization does not match.")

    if approval.decision != "approve":
        _reject("Action approval has not been granted.")

    # Verify mission ownership and target association.
    try:
        mission = (
            db.query(Mission)
            .filter(Mission.id == action.mission_id)
            .one_or_none()
        )
    except SQLAlchemyError as exc:
        raise SimulationDispatchValidationError(
            "Mission could not be safely loaded."
        ) from exc

    if mission is None:
        _reject("Associated mission was not found.")

    if mission.organization_id != organization_id:
        _reject("Mission organization does not match.")

    if mission.asset_id is not None and mission.asset_id != action.target_id:
        _reject("Mission asset does not match the action target.")

    # Verify the target asset.
    try:
        asset = (
            db.query(Asset)
            .filter(
                Asset.id == action.target_id,
                Asset.organization_id == organization_id,
            )
            .one_or_none()
        )
    except SQLAlchemyError as exc:
        raise SimulationDispatchValidationError(
            "Target asset could not be safely loaded."
        ) from exc

    if asset is None:
        _reject("Target asset was not found in this organization.")

    # Always use the latest authorization. Never fall back to an older one.
    try:
        authorization = (
            db.query(AssetAuthorization)
            .filter(
                AssetAuthorization.asset_id == asset.id,
                AssetAuthorization.organization_id == organization_id,
            )
            .order_by(
                AssetAuthorization.updated_at.desc(),
                AssetAuthorization.created_at.desc(),
            )
            .first()
        )
    except SQLAlchemyError as exc:
        raise SimulationDispatchValidationError(
            "Latest asset authorization could not be safely loaded."
        ) from exc

    if authorization is None:
        _reject("No asset authorization record exists.")

    if authorization.organization_id != organization_id:
        _reject("Authorization organization does not match.")

    if authorization.asset_id != asset.id:
        _reject("Authorization asset does not match.")

    # Re-run the existing policy at dispatch-validation time.
    try:
        policy_result = evaluate_action_policy(
            action=action,
            asset=asset,
            approval=approval,
            authorization=authorization,
            emergency_stop=False,
        )
    except Exception as exc:
        raise SimulationDispatchValidationError(
            "Action policy validation failed."
        ) from exc

    if not policy_result.allowed:
        _reject(
            "Action policy rejected dispatch: "
            + str(policy_result.reason)
        )

    return SimulationDispatchValidation(
        execution_record_id=execution.id,
        action_request_id=action.id,
        organization_id=organization_id,
        worker_id=worker.worker_id,
        action_type=action.action_type,
        target_id=asset.id,
    )


def claim_simulation_dispatch(
    db,
    execution_record_id: str,
    worker_registry,
    worker_id: str,
) -> SimulationDispatch:
    """
    Atomically claim one queued execution for simulation-only processing.

    SQLite only. Requires a clean, dedicated SQLAlchemy session.
    Holds the worker eligibility lease until the transaction commits.
    This creates a simulation dispatch record and audit event only.
    It never changes ExecutionRecord.status or performs an operation.
    """

    if db.in_transaction():
        _reject(
            "A clean database session is required for atomic dispatch."
        )

    if not isinstance(worker_id, str) or not worker_id.strip():
        _reject("A valid worker ID is required.")

    try:
        bind = db.get_bind()
        if bind.dialect.name != "sqlite":
            _reject(
                "Atomic simulation dispatch is supported only on SQLite."
            )

        # Acquire the SQLite write reservation before the registry lock.
        connection = db.connection()
        connection.exec_driver_sql("BEGIN IMMEDIATE")

        # Hold eligibility until the database transaction commits.
        with worker_registry.eligible_worker(worker_id.strip()) as worker:

            validation = validate_simulation_dispatch(
                db=db,
                execution_record_id=execution_record_id,
                worker_registry=worker_registry,
                worker_id=worker.worker_id,
            )

            if validation.worker_id != worker.worker_id:
                _reject("Validated worker does not match the leased worker.")

            existing = (
                db.query(SimulationDispatch)
                .filter(
                    SimulationDispatch.execution_record_id
                    == validation.execution_record_id
                )
                .one_or_none()
            )

            if existing is not None:
                _reject(
                    "This execution record already has a simulation dispatch."
                )

            now = datetime.now(timezone.utc)

            dispatch = SimulationDispatch(
                execution_record_id=validation.execution_record_id,
                organization_id=validation.organization_id,
                status="claimed",
                worker_id=worker.worker_id,
                claimed_at=now,
                synthetic_result={
                    "mode": "simulation_only",
                    "execution_started": False,
                    "external_side_effects": False,
                },
            )

            db.add(dispatch)
            db.flush()

            event = SimulationDispatchEvent(
                dispatch_id=dispatch.id,
                organization_id=validation.organization_id,
                event_type="dispatch_claimed",
                worker_id=worker.worker_id,
                details={
                    "mode": "simulation_only",
                    "execution_started": False,
                    "external_side_effects": False,
                },
            )

            db.add(event)
            db.flush()

            # Commit before releasing the worker eligibility lease.
            db.commit()
            db.refresh(dispatch)

            return dispatch

    except Exception as exc:
        db.rollback()

        if isinstance(exc, SimulationDispatchValidationError):
            raise

        if isinstance(exc, WorkerNotEligibleError):
            raise SimulationDispatchValidationError(
                "Dispatch blocked: worker is not eligible."
            ) from exc

        if isinstance(exc, SQLAlchemyError):
            raise SimulationDispatchValidationError(
                "Atomic simulation dispatch claim failed safely."
            ) from exc

        raise
