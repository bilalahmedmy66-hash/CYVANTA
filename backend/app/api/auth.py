from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database.session import get_db
from app.models import User, Organization, Membership, AuditLog
from app.schemas import (
    RegisterRequest,
    LoginRequest,
    UserResponse,
    TokenResponse,
    RegistrationResponse,
)
from app.security.auth import (
    hash_password,
    verify_password,
    create_access_token,
)
from app.security.dependencies import get_current_user
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


def add_audit(
    db,
    action,
    user_id=None,
    organization_id=None,
    request=None,
):
    ip = request.client.host if request and request.client else None

    db.add(
        AuditLog(
            user_id=user_id,
            organization_id=organization_id,
            action=action,
            target_type="authentication",
            details={},
            ip_address=ip,
        )
    )


@router.post("/register", response_model=RegistrationResponse, status_code=201)
def register(
    data: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    email = str(data.email).lower()

    existing = db.query(User).filter(User.email == email).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        )

    user = User(
        email=email,
        password_hash=hash_password(data.password),
    )

    organization = Organization(name=data.organization_name)

    try:
        db.add(user)
        db.add(organization)
        db.flush()

        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            role="owner",
        )

        db.add(membership)

        add_audit(
            db,
            "user.registered",
            user.id,
            organization.id,
            request,
        )

        db.commit()
        db.refresh(user)
        db.refresh(organization)

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Registration could not be completed.",
        )

    return RegistrationResponse(
        user=user,
        organization_id=organization.id,
        organization_name=organization.name,
    )


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    email = str(data.email).lower()

    user = db.query(User).filter(User.email == email).first()

    if (
        user is None
        or not user.is_active
        or not verify_password(data.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

    add_audit(
        db,
        "user.login",
        user.id,
        request=request,
    )

    db.commit()

    token = create_access_token(user.id)

    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
def get_profile(
    user: User = Depends(get_current_user),
):
    return user

@router.get("/organizations")
def list_my_organizations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return only organizations the authenticated user belongs to."""
    memberships = (
        db.query(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .filter(Membership.user_id == user.id)
        .order_by(Organization.name.asc())
        .all()
    )

    return [
        {
            "organization_id": membership.organization_id,
            "organization_name": organization.name,
            "role": membership.role,
        }
        for membership, organization in memberships
    ]
