from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import (
    Asset,
    AssetAuthorization,
    AuthorizationLifecycleEvent,
    AuditLog,
    Membership,
    User,
)
from app.schemas import (
    AssetAuthorizationCreateRequest,
    AssetAuthorizationResponse,
    AssetAuthorizationDecisionRequest,
    AuthorizationLifecycleRequest,
)
from app.security.dependencies import (
    get_current_user,
    get_current_membership,
)

router = APIRouter(
    prefix="/assets",
    tags=["Asset Authorization"],
)


@router.post(
    "/{asset_id}/authorizations",
    response_model=AssetAuthorizationResponse,
    status_code=201,
)
def create_authorization_request(
    asset_id: str,
    data: AssetAuthorizationCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    if membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Organization owner or admin permission required.",
        )

    asset = (
        db.query(Asset)
        .filter(
            Asset.id == asset_id,
            Asset.organization_id == membership.organization_id,
        )
        .first()
    )

    if asset is None:
        raise HTTPException(
            status_code=404,
            detail="Asset not found in this organization.",
        )

    existing_request = (
        db.query(AssetAuthorization)
        .filter(
            AssetAuthorization.asset_id == asset.id,
            AssetAuthorization.organization_id == membership.organization_id,
            AssetAuthorization.status == "pending",
        )
        .first()
    )

    if existing_request is not None:
        raise HTTPException(
            status_code=409,
            detail="This asset already has a pending authorization request.",
        )

    authorization = AssetAuthorization(
        organization_id=membership.organization_id,
        asset_id=asset.id,
        status="pending",
        submitted_by=user.id,
        evidence_type=data.evidence_type,
        evidence_reference=data.evidence_reference,
        scope=data.scope.model_dump(mode="json"),
        valid_from=data.valid_from,
        expires_at=data.expires_at,
    )

    db.add(authorization)
    db.flush()

    db.add(
        AuthorizationLifecycleEvent(
            organization_id=membership.organization_id,
            authorization_id=authorization.id,
            event_type="submitted",
            actor_id=user.id,
            reason="Authorization request submitted.",
            details={
                "asset_id": asset.id,
                "status": "pending",
            },
        )
    )

    db.add(
        AuditLog(
            user_id=user.id,
            organization_id=membership.organization_id,
            action="asset_authorization.submitted",
            target_type="asset_authorization",
            target_id=authorization.id,
            details={
                "asset_id": asset.id,
                "status": "pending",
                "evidence_type": data.evidence_type,
                "scope": data.scope.model_dump(mode="json"),
                "expires_at": data.expires_at.isoformat(),
            },
            ip_address=(
                request.client.host if request.client else None
            ),
        )
    )

    db.commit()
    db.refresh(authorization)

    return authorization

@router.post(
    "/authorizations/{authorization_id}/decision",
    response_model=AssetAuthorizationResponse,
)
def decide_authorization_request(
    authorization_id: str,
    data: AssetAuthorizationDecisionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    if membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Organization owner or admin permission required.",
        )

    authorization = (
        db.query(AssetAuthorization)
        .filter(
            AssetAuthorization.id == authorization_id,
            AssetAuthorization.organization_id == membership.organization_id,
        )
        .first()
    )

    if authorization is None:
        raise HTTPException(
            status_code=404,
            detail="Authorization request not found in this organization.",
        )

    if authorization.submitted_by == user.id:
        raise HTTPException(
            status_code=403,
            detail="The requester cannot review their own authorization request.",
        )

    if authorization.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Only pending authorization requests can be reviewed.",
        )

    now = datetime.now(timezone.utc)

    valid_from = authorization.valid_from
    expires_at = authorization.expires_at

    # SQLite may return timezone-naive datetimes.
    if valid_from.tzinfo is None:
        valid_from = valid_from.replace(tzinfo=timezone.utc)

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if data.decision == "approve":
        if now < valid_from:
            raise HTTPException(
                status_code=409,
                detail="Authorization period has not started.",
            )

        if now >= expires_at:
            raise HTTPException(
                status_code=409,
                detail="Authorization request has expired.",
            )

        asset = (
            db.query(Asset)
            .filter(
                Asset.id == authorization.asset_id,
                Asset.organization_id == membership.organization_id,
            )
            .first()
        )

        if asset is None:
            raise HTTPException(
                status_code=404,
                detail="Associated asset not found in this organization.",
            )
    else:
        asset = None

    # Atomic state transition: only one reviewer can change a pending
    # authorization request. This also protects against duplicate decisions
    # when the database does not support SELECT FOR UPDATE.
    result = db.execute(
        update(AssetAuthorization)
        .where(
            AssetAuthorization.id == authorization_id,
            AssetAuthorization.organization_id == membership.organization_id,
            AssetAuthorization.status == "pending",
        )
        .values(
            status="verified" if data.decision == "approve" else "rejected",
            reviewed_by=user.id,
            reviewed_at=now,
            decision_reason=data.reason,
        )
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This authorization request has already been reviewed.",
        )

    # Authorization verification does NOT enable security assessments.
    if data.decision == "approve":
        asset.authorization_status = "verified"
        asset.assessment_enabled = False

    audit_action = (
        "asset_authorization.approved"
        if data.decision == "approve"
        else "asset_authorization.rejected"
    )

    db.add(
        AuthorizationLifecycleEvent(
            organization_id=membership.organization_id,
            authorization_id=authorization_id,
            event_type="approved" if data.decision == "approve" else "rejected",
            actor_id=user.id,
            reason=data.reason,
            details={
                "asset_id": authorization.asset_id,
                "status": "verified" if data.decision == "approve" else "rejected",
            },
        )
    )

    db.add(
        AuditLog(
            user_id=user.id,
            organization_id=membership.organization_id,
            action=audit_action,
            target_type="asset_authorization",
            target_id=authorization_id,
            details={
                "asset_id": authorization.asset_id,
                "decision": data.decision,
                "reason": data.reason,
                "status": (
                    "verified" if data.decision == "approve" else "rejected"
                ),
                "assessment_enabled": False,
            },
            ip_address=(
                request.client.host if request.client else None
            ),
        )
    )

    try:
        db.commit()
        db.refresh(authorization)
    except Exception:
        db.rollback()
        raise

    return authorization


# ---------------------------------------------------------------------------
# Authorization lifecycle management
# ---------------------------------------------------------------------------

def _normalize_utc(value):
    """Normalize SQLite-naive and timezone-aware datetimes to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_lifecycle_admin(membership):
    if membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Organization owner or admin permission required.",
        )


def _get_lifecycle_authorization(db, authorization_id, organization_id):
    authorization = (
        db.query(AssetAuthorization)
        .filter(
            AssetAuthorization.id == authorization_id,
            AssetAuthorization.organization_id == organization_id,
        )
        .first()
    )

    if authorization is None:
        raise HTTPException(
            status_code=404,
            detail="Authorization request not found in this organization.",
        )

    asset = (
        db.query(Asset)
        .filter(
            Asset.id == authorization.asset_id,
            Asset.organization_id == organization_id,
        )
        .first()
    )

    if asset is None:
        raise HTTPException(
            status_code=404,
            detail="Associated asset not found in this organization.",
        )

    return authorization, asset


def _record_lifecycle_transition(
    db,
    authorization,
    user,
    request,
    event_type,
    reason,
    previous_status,
    new_status,
):
    db.add(
        AuthorizationLifecycleEvent(
            organization_id=authorization.organization_id,
            authorization_id=authorization.id,
            event_type=event_type,
            actor_id=user.id,
            reason=reason,
            details={
                "asset_id": authorization.asset_id,
                "previous_status": previous_status,
                "new_status": new_status,
            },
        )
    )

    db.add(
        AuditLog(
            user_id=user.id,
            organization_id=authorization.organization_id,
            action=f"asset_authorization.{event_type}",
            target_type="asset_authorization",
            target_id=authorization.id,
            details={
                "asset_id": authorization.asset_id,
                "previous_status": previous_status,
                "new_status": new_status,
                "reason": reason,
                "assessment_enabled": False,
            },
            ip_address=request.client.host if request.client else None,
        )
    )


@router.post(
    "/authorizations/{authorization_id}/suspend",
    response_model=AssetAuthorizationResponse,
)
def suspend_authorization(
    authorization_id: str,
    data: AuthorizationLifecycleRequest,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    _require_lifecycle_admin(membership)

    authorization, asset = _get_lifecycle_authorization(
        db, authorization_id, membership.organization_id
    )

    if authorization.status != "verified":
        raise HTTPException(
            status_code=409,
            detail="Only verified authorizations can be suspended.",
        )

    now = datetime.now(timezone.utc)

    result = db.execute(
        update(AssetAuthorization)
        .where(
            AssetAuthorization.id == authorization_id,
            AssetAuthorization.organization_id == membership.organization_id,
            AssetAuthorization.status == "verified",
        )
        .values(
            status="suspended",
            suspended_by=user.id,
            suspended_at=now,
            suspension_reason=data.reason,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Authorization changed before suspension could be completed.",
        )

    previous_status = authorization.status
    asset.authorization_status = "suspended"
    asset.assessment_enabled = False

    _record_lifecycle_transition(
        db,
        authorization,
        user,
        request,
        "suspended",
        data.reason,
        previous_status,
        "suspended",
    )

    try:
        db.commit()
        db.refresh(authorization)
    except Exception:
        db.rollback()
        raise

    return authorization


@router.post(
    "/authorizations/{authorization_id}/reactivate",
    response_model=AssetAuthorizationResponse,
)
def reactivate_authorization(
    authorization_id: str,
    data: AuthorizationLifecycleRequest,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    _require_lifecycle_admin(membership)

    authorization, asset = _get_lifecycle_authorization(
        db, authorization_id, membership.organization_id
    )

    if authorization.submitted_by == user.id:
        raise HTTPException(
            status_code=403,
            detail="The original requester cannot reactivate their own authorization.",
        )

    if authorization.status != "suspended":
        raise HTTPException(
            status_code=409,
            detail="Only suspended authorizations can be reactivated.",
        )

    now = datetime.now(timezone.utc)
    valid_from = _normalize_utc(authorization.valid_from)
    expires_at = _normalize_utc(authorization.expires_at)

    if now < valid_from:
        raise HTTPException(
            status_code=409,
            detail="Authorization validity period has not started.",
        )

    if now >= expires_at:
        raise HTTPException(
            status_code=409,
            detail="Expired authorization cannot be reactivated. Submit a new request.",
        )

    result = db.execute(
        update(AssetAuthorization)
        .where(
            AssetAuthorization.id == authorization_id,
            AssetAuthorization.organization_id == membership.organization_id,
            AssetAuthorization.status == "suspended",
        )
        .values(
            status="verified",
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Authorization changed before reactivation could be completed.",
        )

    previous_status = authorization.status
    asset.authorization_status = "verified"

    # Verification never enables assessment execution.
    asset.assessment_enabled = False

    _record_lifecycle_transition(
        db,
        authorization,
        user,
        request,
        "reactivated",
        data.reason,
        previous_status,
        "verified",
    )

    try:
        db.commit()
        db.refresh(authorization)
    except Exception:
        db.rollback()
        raise

    return authorization


@router.post(
    "/authorizations/{authorization_id}/revoke",
    response_model=AssetAuthorizationResponse,
)
def revoke_authorization(
    authorization_id: str,
    data: AuthorizationLifecycleRequest,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    _require_lifecycle_admin(membership)

    authorization, asset = _get_lifecycle_authorization(
        db, authorization_id, membership.organization_id
    )

    if authorization.status not in ("verified", "suspended"):
        raise HTTPException(
            status_code=409,
            detail="Only verified or suspended authorizations can be revoked.",
        )

    now = datetime.now(timezone.utc)
    previous_status = authorization.status

    result = db.execute(
        update(AssetAuthorization)
        .where(
            AssetAuthorization.id == authorization_id,
            AssetAuthorization.organization_id == membership.organization_id,
            AssetAuthorization.status.in_(("verified", "suspended")),
        )
        .values(
            status="revoked",
            revoked_by=user.id,
            revoked_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Authorization changed before revocation could be completed.",
        )

    asset.authorization_status = "revoked"
    asset.assessment_enabled = False

    _record_lifecycle_transition(
        db,
        authorization,
        user,
        request,
        "revoked",
        data.reason,
        previous_status,
        "revoked",
    )

    try:
        db.commit()
        db.refresh(authorization)
    except Exception:
        db.rollback()
        raise

    return authorization
