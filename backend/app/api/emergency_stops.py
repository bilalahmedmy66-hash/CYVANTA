from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import (
    EmergencyStopState,
    AuditLog,
    User,
    Membership,
)
from app.security.dependencies import (
    get_current_user,
    get_current_membership,
)


router = APIRouter(
    prefix="/emergency-stop",
    tags=["Emergency Stop"],
)


class EmergencyStopChangeRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value):
        value = value.strip()

        if len(value) < 5:
            raise ValueError("Reason must contain at least 5 non-whitespace characters.")

        return value


def require_admin(membership: Membership):
    if membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Organization owner or admin permission required.",
        )


def get_state(db: Session, organization_id: str):
    return (
        db.query(EmergencyStopState)
        .filter(
            EmergencyStopState.organization_id == organization_id
        )
        .first()
    )


def emergency_stop_response(state):
    if state is None:
        return {
            "organization_id": None,
            "is_active": False,
            "reason": None,
            "changed_by": None,
            "updated_at": None,
        }

    return {
        "organization_id": state.organization_id,
        "is_active": state.is_active,
        "reason": state.reason,
        "changed_by": state.changed_by,
        "updated_at": state.updated_at,
    }


@router.get("")
def get_emergency_stop_status(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    state = get_state(db, membership.organization_id)

    response = emergency_stop_response(state)
    response["organization_id"] = membership.organization_id

    return response


@router.post("/activate")
def activate_emergency_stop(
    data: EmergencyStopChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    require_admin(membership)

    state = get_state(db, membership.organization_id)

    if state is None:
        state = EmergencyStopState(
            organization_id=membership.organization_id,
            is_active=True,
            reason=data.reason.strip(),
            changed_by=user.id,
        )
        db.add(state)
    else:
        state.is_active = True
        state.reason = data.reason.strip()
        state.changed_by = user.id

    db.flush()

    db.add(
        AuditLog(
            user_id=user.id,
            organization_id=membership.organization_id,
            action="emergency_stop.activated",
            target_type="emergency_stop",
            target_id=state.id,
            details={"reason": data.reason.strip()},
            ip_address=request.client.host if request.client else None,
        )
    )

    db.commit()
    db.refresh(state)

    return emergency_stop_response(state)


@router.post("/deactivate")
def deactivate_emergency_stop(
    data: EmergencyStopChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    require_admin(membership)

    state = get_state(db, membership.organization_id)

    if state is None:
        state = EmergencyStopState(
            organization_id=membership.organization_id,
            is_active=False,
            reason=data.reason.strip(),
            changed_by=user.id,
        )
        db.add(state)
    else:
        state.is_active = False
        state.reason = data.reason.strip()
        state.changed_by = user.id

    db.flush()

    db.add(
        AuditLog(
            user_id=user.id,
            organization_id=membership.organization_id,
            action="emergency_stop.deactivated",
            target_type="emergency_stop",
            target_id=state.id,
            details={"reason": data.reason.strip()},
            ip_address=request.client.host if request.client else None,
        )
    )

    db.commit()
    db.refresh(state)

    return emergency_stop_response(state)

