from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database.session import get_db
from app.models import (
    ActionRequest,
    ActionApproval,
    Asset,
    AssetAuthorization,
    ExecutionRecord,
    AuditLog,
    User,
    Membership,
)
from app.security.dependencies import (
    get_current_user,
    get_current_membership,
)
from app.action_engine.execution_queue import enqueue_action
from app.action_engine.execution_lifecycle import transition_execution
from app.action_engine.emergency_stop import (
    is_emergency_stop_active,
    EmergencyStopStateUnavailable,
)


router = APIRouter(tags=["Execution Engine"])

def is_duplicate_execution_conflict(exc):
    original = exc.orig

    constraint_name = getattr(
        getattr(original, "diag", None),
        "constraint_name",
        None,
    )

    if constraint_name == "uq_execution_action_request":
        return True

    error_name = getattr(original, "sqlite_errorname", None)
    error_message = str(original)

    return (
        error_name == "SQLITE_CONSTRAINT_UNIQUE"
        and "execution_records.action_request_id" in error_message
    )



def require_admin(membership):
    if membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Organization owner or admin permission required.",
        )


def execution_response(record):
    return {
        "id": record.id,
        "action_request_id": record.action_request_id,
        "organization_id": record.organization_id,
        "status": record.status,
        "result": record.result,
        "verified": record.verified,
        "started_at": record.started_at,
        "completed_at": record.completed_at,
        "created_at": record.created_at,
    }


@router.post("/api/v1/actions/{action_id}/queue", status_code=201)
def queue_action(
    action_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    require_admin(membership)

    action = db.query(ActionRequest).filter(
        ActionRequest.id == action_id,
        ActionRequest.organization_id == membership.organization_id,
    ).first()

    if action is None:
        raise HTTPException(status_code=404, detail="Action not found.")

    if action.target_type != "asset":
        raise HTTPException(
            status_code=409,
            detail="Only asset-targeted actions may enter this queue.",
        )

    approval = db.query(ActionApproval).filter(
        ActionApproval.action_request_id == action.id,
        ActionApproval.organization_id == membership.organization_id,
    ).first()

    asset = db.query(Asset).filter(
        Asset.id == action.target_id,
        Asset.organization_id == membership.organization_id,
    ).first()

    if asset is None:
        raise HTTPException(
            status_code=404,
            detail="Target asset not found in this organization.",
        )

    authorization = (
        db.query(AssetAuthorization)
        .filter(
            AssetAuthorization.asset_id == asset.id,
            AssetAuthorization.organization_id == membership.organization_id,
            AssetAuthorization.status == "verified",
        )
        .order_by(
            AssetAuthorization.reviewed_at.desc(),
            AssetAuthorization.created_at.desc(),
        )
        .first()
    )

    try:
        emergency_stop = is_emergency_stop_active(
            db=db,
            organization_id=membership.organization_id,
        )
    except EmergencyStopStateUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Execution queue unavailable because Emergency Stop state could not be verified.",
        ) from exc


    try:
        record = enqueue_action(
            db=db,
            action=action,
            asset=asset,
            approval=approval,
            authorization=authorization,
            emergency_stop=emergency_stop,
            return_created=True,
        )
        record, created = record
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()

        if not is_duplicate_execution_conflict(exc):
            raise

        record = (
            db.query(ExecutionRecord)
            .filter(
                ExecutionRecord.action_request_id == action.id,
                ExecutionRecord.organization_id == membership.organization_id,
            )
            .first()
        )

        if record is None:
            raise

        created = False

    if created:
        db.add(
            AuditLog(
                user_id=user.id,
                organization_id=membership.organization_id,
                action="execution.queued",
                target_type="execution_record",
                target_id=record.id,
                details={
                    "action_request_id": action.id,
                    "action_type": action.action_type,
                    "execution_started": False,
                    "authorization_id": authorization.id if authorization else None,
                },
                ip_address=request.client.host if request.client else None,
            )
        )
    db.commit()
    db.refresh(record)

    return execution_response(record)


@router.post("/api/v1/executions/{execution_id}/cancel")
def cancel_execution(
    execution_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    require_admin(membership)

    record = (
        db.query(ExecutionRecord)
        .filter(
            ExecutionRecord.id == execution_id,
            ExecutionRecord.organization_id == membership.organization_id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Execution record not found.",
        )

    previous_status = record.status

    try:
        record = transition_execution(
            db=db,
            execution_id=record.id,
            target_status="cancelled",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    db.add(
        AuditLog(
            user_id=user.id,
            organization_id=membership.organization_id,
            action="execution.cancelled",
            target_type="execution_record",
            target_id=record.id,
            details={
                "previous_status": previous_status,
                "new_status": "cancelled",
                "execution_started": False,
            },
            ip_address=request.client.host if request.client else None,
        )
    )

    db.commit()
    db.refresh(record)

    return execution_response(record)


@router.get("/api/v1/executions")
def list_executions(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    records = (
        db.query(ExecutionRecord)
        .filter(
            ExecutionRecord.organization_id == membership.organization_id
        )
        .order_by(ExecutionRecord.created_at.desc())
        .all()
    )

    return [execution_response(record) for record in records]


@router.get("/api/v1/executions/{execution_id}")
def get_execution(
    execution_id: str,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    record = db.query(ExecutionRecord).filter(
        ExecutionRecord.id == execution_id,
        ExecutionRecord.organization_id == membership.organization_id,
    ).first()

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Execution record not found.",
        )

    return execution_response(record)
