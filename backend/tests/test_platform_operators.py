import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import PlatformOperator, PlatformOperatorEvent, User
from scripts.platform_operators import (
    ProvisioningError,
    bootstrap_operator,
    grant_operator,
    revoke_operator,
    list_operators,
)


@pytest.fixture
def db():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        session.add_all([
            User(email="first@example.com", password_hash="not-a-real-password-hash", is_active=True),
            User(email="second@example.com", password_hash="not-a-real-password-hash", is_active=True),
            User(email="inactive@example.com", password_hash="not-a-real-password-hash", is_active=False),
        ])
        session.commit()
        yield session
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


def bootstrap(db):
    return bootstrap_operator(
        db, "first@example.com", "Initial trusted local bootstrap", "BOOTSTRAP first@example.com"
    )


def grant_second(db):
    return grant_operator(
        db, "first@example.com", "second@example.com", "Approved platform operations access",
        "GRANT second@example.com",
    )


def test_bootstrap_creates_first_operator_and_immutable_event(db):
    operator = bootstrap(db)
    assert operator.is_active is True
    events = db.scalars(select(PlatformOperatorEvent)).all()
    assert len(events) == 1
    assert events[0].event_type == "bootstrap_granted"
    assert events[0].actor_operator_id is None


def test_bootstrap_is_closed_after_first_active_operator(db):
    bootstrap(db)
    with pytest.raises(ProvisioningError, match="Bootstrap is closed"):
        bootstrap_operator(
            db, "second@example.com", "Another bootstrap attempt", "BOOTSTRAP second@example.com"
        )


def test_bootstrap_requires_exact_confirmation(db):
    with pytest.raises(ProvisioningError, match="confirmation"):
        bootstrap_operator(db, "first@example.com", "Valid reason text", "yes")


def test_grant_requires_active_operator_actor(db):
    with pytest.raises(ProvisioningError, match="not an active platform operator"):
        grant_second(db)


def test_grant_and_revoke_append_history(db):
    bootstrap(db)
    second = grant_second(db)
    assert second.is_active is True
    revoked = revoke_operator(
        db, "first@example.com", "second@example.com", "Access no longer required",
        "REVOKE second@example.com",
    )
    assert revoked.is_active is False
    events = db.scalars(
        select(PlatformOperatorEvent).where(PlatformOperatorEvent.target_user_id == second.user_id)
    ).all()
    assert [event.event_type for event in events] == ["granted", "revoked"]


def test_cannot_revoke_last_active_operator(db):
    bootstrap(db)
    with pytest.raises(ProvisioningError, match="last active"):
        revoke_operator(
            db, "first@example.com", "first@example.com", "Emergency removal requested",
            "REVOKE first@example.com",
        )


def test_reactivation_reuses_unique_operator_record_and_appends_event(db):
    bootstrap(db)
    grant_second(db)
    revoke_operator(
        db, "first@example.com", "second@example.com", "Temporary access removal",
        "REVOKE second@example.com",
    )
    reactivated = grant_second(db)
    assert reactivated.is_active is True
    assert len(db.scalars(
        select(PlatformOperator).where(PlatformOperator.user_id == reactivated.user_id)
    ).all()) == 1
    events = db.scalars(
        select(PlatformOperatorEvent).where(PlatformOperatorEvent.target_user_id == reactivated.user_id)
    ).all()
    assert [event.event_type for event in events] == ["granted", "revoked", "reactivated"]


def test_inactive_target_user_cannot_be_granted(db):
    bootstrap(db)
    with pytest.raises(ProvisioningError, match="account is inactive"):
        grant_operator(
            db, "first@example.com", "inactive@example.com", "Approved access request",
            "GRANT inactive@example.com",
        )


def test_operator_list_includes_active_and_revoked_records(db):
    bootstrap(db)
    grant_second(db)
    rows = list_operators(db)
    assert len(rows) == 2
    assert {user.email for _, user in rows} == {"first@example.com", "second@example.com"}


def test_reason_must_be_meaningful(db):
    with pytest.raises(ProvisioningError, match="at least 5"):
        bootstrap_operator(db, "first@example.com", "  no ", "BOOTSTRAP first@example.com")
