"""Local-only provisioning CLI for CYVANTA platform operators.

Run from the backend directory:
    python scripts/platform_operators.py bootstrap --email user@example.com
    python scripts/platform_operators.py grant --actor actor@example.com --email user@example.com
    python scripts/platform_operators.py revoke --actor actor@example.com --email user@example.com
    python scripts/platform_operators.py list

Local OS/database access is the trust boundary. This tool never creates users,
never grants organization roles, and exposes no HTTP provisioning endpoint.
"""
from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# CYVANTA_BACKEND_ROOT_IMPORT_FIX
# Resolve imports, .env and relative database URLs from backend root.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)

from typing import Callable

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import SessionLocal, engine
from app.models import PlatformOperator, PlatformOperatorEvent, User

MIGRATION_VERSION = "20261108_001_active_defense_audit_immutability"


class ProvisioningError(Exception):
    """Expected, safe-to-display provisioning failure."""


def _require_ready_database() -> None:
    inspector = inspect(engine)
    required = {"users", "platform_operators", "platform_operator_events", "cyvanta_schema_migrations"}
    existing = set(inspector.get_table_names())
    missing = sorted(required - existing)
    if missing:
        raise ProvisioningError(
            "Database schema is not ready. Start the application once with the intended "
            f"database, then retry. Missing tables: {', '.join(missing)}"
        )
    with engine.connect() as connection:
        applied = connection.execute(
            text("SELECT version FROM cyvanta_schema_migrations WHERE version = :version"),
            {"version": MIGRATION_VERSION},
        ).scalar_one_or_none()
    if applied != MIGRATION_VERSION:
        raise ProvisioningError(
            "Active Defense audit migration is not recorded. Start the application once "
            "with the intended database, then retry."
        )


def _clean_reason(reason: str) -> str:
    cleaned = reason.strip()
    if len(cleaned) < 5:
        raise ProvisioningError("Reason must contain at least 5 non-space characters.")
    if len(cleaned) > 1000:
        raise ProvisioningError("Reason must be 1000 characters or fewer.")
    return cleaned


def _active_user(db: Session, email: str) -> User:
    normalized = email.strip().lower()
    if not normalized:
        raise ProvisioningError("Email is required.")
    user = db.scalar(select(User).where(User.email == normalized))
    if user is None:
        raise ProvisioningError("No existing user has that email. This CLI never creates users.")
    if not user.is_active:
        raise ProvisioningError("The target user account is inactive.")
    return user


def _active_operator_for_user(db: Session, user: User) -> PlatformOperator:
    operator = db.scalar(
        select(PlatformOperator).where(
            PlatformOperator.user_id == user.id,
            PlatformOperator.is_active.is_(True),
        )
    )
    if operator is None:
        raise ProvisioningError("The acting user is not an active platform operator.")
    return operator


def bootstrap_operator(db: Session, email: str, reason: str, confirmation: str) -> PlatformOperator:
    """Create the first operator only; bootstrap is permanently closed afterward."""
    reason = _clean_reason(reason)
    normalized = email.strip().lower()
    if confirmation != f"BOOTSTRAP {normalized}":
        raise ProvisioningError("Bootstrap confirmation did not match.")
    try:
        if db.scalar(select(PlatformOperator.id).where(PlatformOperator.is_active.is_(True)).limit(1)):
            raise ProvisioningError("Bootstrap is closed: an active platform operator already exists.")
        user = _active_user(db, normalized)
        existing = db.scalar(select(PlatformOperator).where(PlatformOperator.user_id == user.id))
        if existing is not None:
            raise ProvisioningError(
                "This user already has an operator record. Use the grant command with an active operator."
            )
        operator = PlatformOperator(
            user_id=user.id,
            is_active=True,
            granted_by_operator_id=None,
            grant_reason=reason,
        )
        db.add(operator)
        db.flush()
        db.add(
            PlatformOperatorEvent(
                operator_id=operator.id,
                target_user_id=user.id,
                event_type="bootstrap_granted",
                actor_operator_id=None,
                reason=reason,
            )
        )
        db.commit()
        db.refresh(operator)
        return operator
    except Exception:
        db.rollback()
        raise


def grant_operator(
    db: Session, actor_email: str, target_email: str, reason: str, confirmation: str
) -> PlatformOperator:
    reason = _clean_reason(reason)
    target_normalized = target_email.strip().lower()
    if confirmation != f"GRANT {target_normalized}":
        raise ProvisioningError("Grant confirmation did not match.")
    try:
        actor_user = _active_user(db, actor_email)
        actor = _active_operator_for_user(db, actor_user)
        target_user = _active_user(db, target_normalized)
        if actor_user.id == target_user.id:
            raise ProvisioningError("An operator cannot grant platform access to themselves.")
        existing = db.scalar(select(PlatformOperator).where(PlatformOperator.user_id == target_user.id))
        if existing is None:
            operator = PlatformOperator(
                user_id=target_user.id,
                is_active=True,
                granted_by_operator_id=actor.id,
                grant_reason=reason,
            )
            event_type = "granted"
            db.add(operator)
            db.flush()
        else:
            if existing.is_active:
                raise ProvisioningError("This user is already an active platform operator.")
            existing.is_active = True
            existing.granted_by_operator_id = actor.id
            existing.grant_reason = reason
            existing.granted_at = datetime.now(timezone.utc)
            existing.revoked_at = None
            operator = existing
            event_type = "reactivated"
        db.add(
            PlatformOperatorEvent(
                operator_id=operator.id,
                target_user_id=target_user.id,
                event_type=event_type,
                actor_operator_id=actor.id,
                reason=reason,
            )
        )
        db.commit()
        db.refresh(operator)
        return operator
    except Exception:
        db.rollback()
        raise


def revoke_operator(
    db: Session, actor_email: str, target_email: str, reason: str, confirmation: str
) -> PlatformOperator:
    reason = _clean_reason(reason)
    target_normalized = target_email.strip().lower()
    if confirmation != f"REVOKE {target_normalized}":
        raise ProvisioningError("Revocation confirmation did not match.")
    try:
        actor_user = _active_user(db, actor_email)
        actor = _active_operator_for_user(db, actor_user)
        target_user = _active_user(db, target_normalized)
        target = db.scalar(select(PlatformOperator).where(PlatformOperator.user_id == target_user.id))
        if target is None or not target.is_active:
            raise ProvisioningError("Target user is not an active platform operator.")
        active_total = len(
            db.scalars(select(PlatformOperator.id).where(PlatformOperator.is_active.is_(True))).all()
        )
        if active_total <= 1:
            raise ProvisioningError("Cannot revoke the last active platform operator.")
        if actor_user.id == target_user.id:
            raise ProvisioningError("Self-revocation is not permitted through this CLI.")
        target.is_active = False
        target.revoked_at = datetime.now(timezone.utc)
        db.add(
            PlatformOperatorEvent(
                operator_id=target.id,
                target_user_id=target_user.id,
                event_type="revoked",
                actor_operator_id=actor.id,
                reason=reason,
            )
        )
        db.commit()
        db.refresh(target)
        return target
    except Exception:
        db.rollback()
        raise


def list_operators(db: Session) -> list[tuple[PlatformOperator, User]]:
    rows = db.execute(
        select(PlatformOperator, User)
        .join(User, User.id == PlatformOperator.user_id)
        .order_by(PlatformOperator.granted_at.asc())
    ).all()
    return [(operator, user) for operator, user in rows]


def _prompt_reason() -> str:
    return input("Reason (minimum 5 characters): ").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CYVANTA local platform-operator provisioning")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser("bootstrap", help="Provision the first platform operator")
    bootstrap.add_argument("--email", required=True)

    grant = sub.add_parser("grant", help="Grant or reactivate a platform operator")
    grant.add_argument("--actor", required=True, help="Email of the active acting platform operator")
    grant.add_argument("--email", required=True, help="Existing active target user email")

    revoke = sub.add_parser("revoke", help="Revoke a platform operator")
    revoke.add_argument("--actor", required=True, help="Email of the active acting platform operator")
    revoke.add_argument("--email", required=True, help="Existing active target user email")

    sub.add_parser("list", help="List platform operators")

    args = parser.parse_args(argv)
    try:
        _require_ready_database()
        with SessionLocal() as db:
            if args.command == "bootstrap":
                email = args.email.strip().lower()
                user = _active_user(db, email)
                print(f"Bootstrap target: {user.email} (user ID: {user.id})")
                reason = _prompt_reason()
                expected = f"BOOTSTRAP {email}"
                confirmation = input(f"Type exactly '{expected}' to continue: ")
                operator = bootstrap_operator(db, email, reason, confirmation)
                print(f"SUCCESS: first platform operator provisioned (operator ID: {operator.id}).")
            elif args.command == "grant":
                target_email = args.email.strip().lower()
                user = _active_user(db, target_email)
                print(f"Grant target: {user.email} (user ID: {user.id})")
                reason = _prompt_reason()
                expected = f"GRANT {target_email}"
                confirmation = input(f"Type exactly '{expected}' to continue: ")
                operator = grant_operator(db, args.actor, target_email, reason, confirmation)
                print(f"SUCCESS: platform operator active (operator ID: {operator.id}).")
            elif args.command == "revoke":
                target_email = args.email.strip().lower()
                user = _active_user(db, target_email)
                print(f"Revocation target: {user.email} (user ID: {user.id})")
                reason = _prompt_reason()
                expected = f"REVOKE {target_email}"
                confirmation = input(f"Type exactly '{expected}' to continue: ")
                operator = revoke_operator(db, args.actor, target_email, reason, confirmation)
                print(f"SUCCESS: platform operator revoked (operator ID: {operator.id}).")
            else:
                rows = list_operators(db)
                if not rows:
                    print("No platform operator records found.")
                for operator, user in rows:
                    status = "ACTIVE" if operator.is_active else "REVOKED"
                    print(f"{status:8} {user.email} | operator_id={operator.id} | user_id={user.id}")
        return 0
    except (ProvisioningError, SQLAlchemyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
