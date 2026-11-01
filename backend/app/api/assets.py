from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import Asset, AuditLog, User, Membership
from app.schemas import AssetCreateRequest, AssetResponse
from app.security.dependencies import (
    get_current_user,
    get_current_membership,
)

router = APIRouter(prefix="/assets", tags=["Asset Management"])


@router.post("", response_model=AssetResponse, status_code=201)
def register_asset(
    data: AssetCreateRequest,
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

    if data.authorization_confirmed is not True:
        raise HTTPException(
            status_code=400,
            detail="Explicit authorization confirmation is required.",
        )

    asset = Asset(
        organization_id=membership.organization_id,
        name=data.name,
        asset_type=data.asset_type,
        identifier=data.identifier,
        authorization_reference=data.authorization_reference,
        authorization_status="declared",
        assessment_enabled=False,
        created_by=user.id,
    )

    db.add(asset)
    db.flush()

    ip = request.client.host if request.client else None

    db.add(
        AuditLog(
            user_id=user.id,
            organization_id=membership.organization_id,
            action="asset.registered",
            target_type="asset",
            target_id=asset.id,
            details={
                "asset_type": asset.asset_type,
                "authorization_status": "declared",
            },
            ip_address=ip,
        )
    )

    db.commit()
    db.refresh(asset)

    return asset


@router.get("", response_model=list[AssetResponse])
def list_assets(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    return (
        db.query(Asset)
        .filter(
            Asset.organization_id == membership.organization_id
        )
        .order_by(Asset.created_at.desc())
        .all()
    )
