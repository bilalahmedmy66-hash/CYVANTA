from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import (
    PlatformDetectionFinding,
    PlatformDetectionFindingEvent,
    PlatformOperator,
    User,
)
from app.security.dependencies import get_current_user


router = APIRouter(
    prefix="/platform/detections",
    tags=["Platform Detection and Alerts"],
)


VALID_STATUSES = {"open", "acknowledged", "resolved"}


class FindingStatusChangeRequest(BaseModel):
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


def get_active_platform_operator(user: User, db: Session):
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


def finding_response(finding):
    return {
        "id": finding.id,
        "rule_id": finding.rule_id,
        "severity": finding.severity,
        "status": finding.status,
        "title": finding.title,
        "description": finding.description,
        "evidence": finding.evidence,
        "first_detected_at": finding.first_detected_at,
        "last_detected_at": finding.last_detected_at,
        "occurrence_count": finding.occurrence_count,
        "created_at": finding.created_at,
        "updated_at": finding.updated_at,
    }


def event_response(event):
    return {
        "id": event.id,
        "event_type": event.event_type,
        "reason": event.reason,
        "details": event.details,
        "created_at": event.created_at,
    }


@router.get("")
def list_platform_findings(
    status: str | None = None,
    severity: str | None = None,
    rule_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_active_platform_operator(user, db)

    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail="Invalid finding status filter.",
        )

    query = db.query(PlatformDetectionFinding)

    if status:
        query = query.filter(
            PlatformDetectionFinding.status == status
        )

    if severity:
        query = query.filter(
            PlatformDetectionFinding.severity == severity
        )

    if rule_id:
        query = query.filter(
            PlatformDetectionFinding.rule_id == rule_id
        )

    total = query.count()

    findings = (
        query.order_by(
            PlatformDetectionFinding.last_detected_at.desc(),
            PlatformDetectionFinding.id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": [finding_response(item) for item in findings],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{finding_id}")
def get_platform_finding(
    finding_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_active_platform_operator(user, db)

    finding = (
        db.query(PlatformDetectionFinding)
        .filter(PlatformDetectionFinding.id == finding_id)
        .one_or_none()
    )

    if finding is None:
        raise HTTPException(
            status_code=404,
            detail="Detection finding not found.",
        )

    events = (
        db.query(PlatformDetectionFindingEvent)
        .filter(
            PlatformDetectionFindingEvent.finding_id == finding_id
        )
        .order_by(
            PlatformDetectionFindingEvent.created_at.asc(),
            PlatformDetectionFindingEvent.id.asc(),
        )
        .all()
    )

    response = finding_response(finding)
    response["events"] = [event_response(event) for event in events]

    return response


def change_finding_status(
    db: Session,
    user_id: str,
    finding_id: str,
    new_status: str,
    event_type: str,
    reason: str,
):
    """
    Atomically change finding status and append immutable lifecycle history.
    Recheck operator authorization inside the write transaction.
    """

    try:
        # Clear any read transaction before acquiring the SQLite write lock.
        db.rollback()

        connection = db.connection()

        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")

        operator_query = db.query(PlatformOperator).filter(
            PlatformOperator.user_id == user_id,
            PlatformOperator.is_active.is_(True),
        )

        if connection.dialect.name != "sqlite":
            operator_query = operator_query.with_for_update()

        operator = operator_query.one_or_none()

        if operator is None:
            db.rollback()
            raise HTTPException(
                status_code=403,
                detail="Active platform operator permission required.",
            )

        finding_query = db.query(PlatformDetectionFinding).filter(
            PlatformDetectionFinding.id == finding_id
        )

        if connection.dialect.name != "sqlite":
            finding_query = finding_query.with_for_update()

        finding = finding_query.one_or_none()

        if finding is None:
            db.rollback()
            raise HTTPException(
                status_code=404,
                detail="Detection finding not found.",
            )

        allowed_transitions = {
            "acknowledged": {"open"},
            "resolved": {"open", "acknowledged"},
        }

        if finding.status not in allowed_transitions[new_status]:
            current_status = finding.status
            db.rollback()

            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot change finding from "
                    f"'{current_status}' to '{new_status}'."
                ),
            )

        previous_status = finding.status
        finding.status = new_status

        db.add(
            PlatformDetectionFindingEvent(
                finding_id=finding.id,
                event_type=event_type,
                reason=reason,
                details={
                    "actor_operator_id": operator.id,
                    "previous_status": previous_status,
                    "new_status": new_status,
                },
            )
        )

        db.commit()
        db.refresh(finding)

        return finding_response(finding)

    except HTTPException:
        raise

    except Exception:
        db.rollback()
        raise


@router.post("/{finding_id}/acknowledge")
def acknowledge_platform_finding(
    finding_id: str,
    data: FindingStatusChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return change_finding_status(
        db=db,
        user_id=user.id,
        finding_id=finding_id,
        new_status="acknowledged",
        event_type="acknowledged",
        reason=data.reason,
    )


@router.post("/{finding_id}/resolve")
def resolve_platform_finding(
    finding_id: str,
    data: FindingStatusChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return change_finding_status(
        db=db,
        user_id=user.id,
        finding_id=finding_id,
        new_status="resolved",
        event_type="resolved",
        reason=data.reason,
    )
