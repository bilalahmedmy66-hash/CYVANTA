from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import (
    PlatformEmergencyStopState,
    PlatformOperator,
    User,
)
from app.security.dependencies import get_current_user
from app.action_engine.platform_emergency_stop import (
    InvalidPlatformStopReason,
    PlatformEmergencyStopStateUnavailable,
    PlatformOperatorRequired,
    is_platform_emergency_stop_active,
    set_platform_emergency_stop,
)


router = APIRouter(
    prefix="/platform/emergency-stop",
    tags=["Platform Emergency Stop"],
)


class PlatformEmergencyStopChangeRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value):
        value = value.strip()

        if len(value) < 5:
            raise ValueError(
                "Reason must contain at least 5 non-whitespace characters."
            )

        return value


def get_active_platform_operator(
    user: User,
    db: Session,
) -> PlatformOperator:
    operator = (
        db.query(PlatformOperator)
        .filter(
            PlatformOperator.user_id == user.id,
            PlatformOperator.is_active.is_(True),
        )
        .one_or_none()
    )

    if operator is None:
        raise HTTPException(
            status_code=403,
            detail="Active platform operator permission required.",
        )

    return operator


def platform_stop_response(state, is_active):
    if state is None:
        return {
            "is_active": is_active,
            "reason": None,
            "changed_by_operator_id": None,
            "updated_at": None,
        }

    return {
        "is_active": is_active,
        "reason": state.reason,
        "changed_by_operator_id": state.changed_by_operator_id,
        "updated_at": state.updated_at,
    }


@router.get("")
def get_platform_emergency_stop_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_active_platform_operator(user, db)

    try:
        is_active = is_platform_emergency_stop_active(db)

        state = (
            db.query(PlatformEmergencyStopState)
            .filter(PlatformEmergencyStopState.id == "platform-master")
            .one_or_none()
        )

        return platform_stop_response(state, is_active)

    except PlatformEmergencyStopStateUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Platform emergency-stop state cannot be verified.",
        )


@router.post("/activate")
def activate_platform_emergency_stop(
    data: PlatformEmergencyStopChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    operator = get_active_platform_operator(user, db)

    try:
        state = set_platform_emergency_stop(
            db=db,
            operator_id=operator.id,
            is_active=True,
            reason=data.reason,
        )

        return platform_stop_response(state, True)

    except PlatformOperatorRequired:
        raise HTTPException(
            status_code=403,
            detail="Active platform operator permission required.",
        )

    except (InvalidPlatformStopReason, ValueError):
        raise HTTPException(
            status_code=422,
            detail="A valid emergency-stop reason is required.",
        )

    except PlatformEmergencyStopStateUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Platform emergency-stop change could not be completed.",
        )


@router.post("/deactivate")
def deactivate_platform_emergency_stop(
    data: PlatformEmergencyStopChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    operator = get_active_platform_operator(user, db)

    try:
        state = set_platform_emergency_stop(
            db=db,
            operator_id=operator.id,
            is_active=False,
            reason=data.reason,
        )

        return platform_stop_response(state, False)

    except PlatformOperatorRequired:
        raise HTTPException(
            status_code=403,
            detail="Active platform operator permission required.",
        )

    except (InvalidPlatformStopReason, ValueError):
        raise HTTPException(
            status_code=422,
            detail="A valid emergency-stop reason is required.",
        )

    except PlatformEmergencyStopStateUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Platform emergency-stop change could not be completed.",
        )
