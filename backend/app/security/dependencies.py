import jwt

from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import User, Membership
from app.security.auth import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")

        if not user_id:
            raise unauthorized

    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized

    user = db.query(User).filter(User.id == user_id).first()

    if user is None or not user.is_active:
        raise unauthorized

    return user


def get_current_membership(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    organization_id: str | None = Header(
        default=None,
        alias="X-Organization-ID",
    ),
):
    query = db.query(Membership).filter(
        Membership.user_id == user.id
    )

    if organization_id:
        query = query.filter(
            Membership.organization_id == organization_id
        )

    membership = query.first()

    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="You do not belong to this organization.",
        )

    return membership
