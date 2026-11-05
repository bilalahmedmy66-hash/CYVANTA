import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models import (
    AuditLog,
    Membership,
    Organization,
    OrganizationInvitation,
    User,
)
from app.schemas import (
    OrganizationInvitationAcceptRequest,
    OrganizationInvitationCreateRequest,
)
from app.security.dependencies import get_current_user, get_current_membership

router = APIRouter(prefix="/organizations", tags=["Organization Membership"])


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _audit(db, action, user_id, organization_id, target_id, details, request):
    db.add(
        AuditLog(
            user_id=user_id,
            organization_id=organization_id,
            action=action,
            target_type="organization_invitation",
            target_id=target_id,
            details=details,
            ip_address=request.client.host if request.client else None,
        )
    )


@router.post("/invitations", status_code=201)
def create_invitation(
    data: OrganizationInvitationCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Organization owner permission required.")

    email = str(data.email).strip().lower()
    if email == user.email.lower():
        raise HTTPException(status_code=400, detail="You cannot invite yourself.")

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        existing_membership = db.query(Membership).filter(
            Membership.user_id == existing_user.id,
            Membership.organization_id == membership.organization_id,
        ).first()
        if existing_membership:
            raise HTTPException(status_code=409, detail="This user is already an organization member.")

    now = datetime.now(timezone.utc)
    active_invitation = db.query(OrganizationInvitation).filter(
        OrganizationInvitation.organization_id == membership.organization_id,
        OrganizationInvitation.email == email,
        OrganizationInvitation.accepted_at.is_(None),
        OrganizationInvitation.revoked_at.is_(None),
    ).all()
    for previous in active_invitation:
        if _utc(previous.expires_at) > now:
            raise HTTPException(status_code=409, detail="An active invitation already exists for this email.")
        previous.revoked_at = now

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    invitation = OrganizationInvitation(
        organization_id=membership.organization_id,
        email=email,
        role="reviewer",
        token_hash=token_hash,
        expires_at=now + timedelta(hours=48),
        created_by=user.id,
    )
    db.add(invitation)
    db.flush()

    _audit(
        db,
        "organization.invitation_created",
        user.id,
        membership.organization_id,
        invitation.id,
        {"email": email, "role": "reviewer", "expires_at": invitation.expires_at.isoformat()},
        request,
    )

    # No email provider is configured. Expose the raw token only in development.
    if settings.app_env.lower() not in ("development", "dev", "test"):
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Invitation delivery is not configured for this environment.",
        )

    db.commit()
    db.refresh(invitation)
    return {
        "id": invitation.id,
        "organization_id": invitation.organization_id,
        "email": invitation.email,
        "role": invitation.role,
        "expires_at": invitation.expires_at,
        "delivery_mode": "development_handoff",
        "invitation_token": raw_token,
        "message": "Development handoff only. Share this token securely with the invited person.",
    }


@router.get("/invitations")
def list_invitations(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Organization owner permission required.")

    records = db.query(OrganizationInvitation).filter(
        OrganizationInvitation.organization_id == membership.organization_id
    ).order_by(OrganizationInvitation.created_at.desc()).all()

    return [
        {
            "id": item.id,
            "email": item.email,
            "role": item.role,
            "expires_at": item.expires_at,
            "accepted_at": item.accepted_at,
            "revoked_at": item.revoked_at,
            "created_at": item.created_at,
            "status": (
                "accepted" if item.accepted_at else
                "revoked" if item.revoked_at else
                "expired" if _utc(item.expires_at) <= datetime.now(timezone.utc) else
                "pending"
            ),
        }
        for item in records
    ]


@router.post("/invitations/accept")
def accept_invitation(
    data: OrganizationInvitationAcceptRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    token_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    invitation = db.query(OrganizationInvitation).filter(
        OrganizationInvitation.token_hash == token_hash
    ).first()

    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation is invalid or unavailable.")
    if invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Invitation has already been used or revoked.")
    if _utc(invitation.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Invitation has expired.")
    if user.email.lower() != invitation.email.lower():
        raise HTTPException(status_code=403, detail="Sign in with the email address this invitation was sent to.")

    existing = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.organization_id == invitation.organization_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="You are already a member of this organization.")

    # Atomic one-time claim: concurrent acceptance attempts cannot both succeed.
    claimed = db.execute(
        update(OrganizationInvitation)
        .where(
            OrganizationInvitation.id == invitation.id,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
        .values(accepted_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invitation has already been used.")

    db.add(
        Membership(
            user_id=user.id,
            organization_id=invitation.organization_id,
            role="reviewer",
        )
    )
    _audit(
        db,
        "organization.invitation_accepted",
        user.id,
        invitation.organization_id,
        invitation.id,
        {"email": user.email.lower(), "role": "reviewer"},
        request,
    )
    db.commit()

    organization = db.query(Organization).filter(
        Organization.id == invitation.organization_id
    ).first()
    return {
        "message": "Invitation accepted.",
        "organization_id": invitation.organization_id,
        "organization_name": organization.name if organization else None,
        "role": "reviewer",
    }


@router.get("/members")
def list_members(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Organization owner permission required.")

    rows = (
        db.query(Membership, User)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.organization_id == membership.organization_id)
        .order_by(User.email.asc())
        .all()
    )
    return [
        {"user_id": member.user_id, "email": user.email, "role": member.role}
        for member, user in rows
    ]


@router.delete("/members/{user_id}", status_code=200)
def remove_member(
    user_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Organization owner permission required.")
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot remove your own membership.")

    target = db.query(Membership).filter(
        Membership.user_id == user_id,
        Membership.organization_id == membership.organization_id,
    ).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Organization member not found.")
    if target.role == "owner":
        raise HTTPException(status_code=409, detail="An owner membership cannot be removed through this endpoint.")

    db.delete(target)
    _audit(
        db,
        "organization.member_removed",
        user.id,
        membership.organization_id,
        user_id,
        {"removed_role": target.role},
        request,
    )
    db.commit()
    return {"message": "Organization membership removed."}
