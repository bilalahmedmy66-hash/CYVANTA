import pytest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import (
    PlatformEmergencyStopEvent,
    PlatformEmergencyStopState,
    PlatformOperator,
    User,
)
from app.action_engine.platform_emergency_stop import (
    PLATFORM_STOP_STATE_ID,
    InvalidPlatformStopReason,
    PlatformEmergencyStopStateUnavailable,
    PlatformOperatorRequired,
    is_platform_emergency_stop_active,
    set_platform_emergency_stop,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    session = TestingSession()

    user = User(
        id="test-user-001",
        email="platform-operator@example.test",
        password_hash="test-only-password-hash",
        is_active=True,
    )
    session.add(user)
    session.flush()

    operator = PlatformOperator(
        id="test-operator-001",
        user_id=user.id,
        is_active=True,
        grant_reason="Test fixture operator",
    )
    session.add(operator)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_missing_state_means_platform_is_stopped(db):
    assert is_platform_emergency_stop_active(db) is True


def test_active_state_means_platform_is_stopped(db):
    db.add(
        PlatformEmergencyStopState(
            id=PLATFORM_STOP_STATE_ID,
            is_active=True,
            reason="Test stop",
        )
    )
    db.commit()

    assert is_platform_emergency_stop_active(db) is True


def test_inactive_state_means_platform_is_released(db):
    db.add(
        PlatformEmergencyStopState(
            id=PLATFORM_STOP_STATE_ID,
            is_active=False,
            reason="Test release",
        )
    )
    db.commit()

    assert is_platform_emergency_stop_active(db) is False


def test_malformed_state_fails_closed(db):
    db.add(
        PlatformEmergencyStopState(
            id="unexpected-state-id",
            is_active=False,
            reason="Malformed test state",
        )
    )
    db.commit()

    with pytest.raises(PlatformEmergencyStopStateUnavailable):
        is_platform_emergency_stop_active(db)


def test_multiple_state_rows_fail_closed(db):
    db.add_all([
        PlatformEmergencyStopState(
            id=PLATFORM_STOP_STATE_ID,
            is_active=False,
            reason="First test state",
        ),
        PlatformEmergencyStopState(
            id="unexpected-second-state",
            is_active=False,
            reason="Second test state",
        ),
    ])
    db.commit()

    with pytest.raises(PlatformEmergencyStopStateUnavailable):
        is_platform_emergency_stop_active(db)


def test_inactive_operator_cannot_change_platform_stop(db):
    operator = db.query(PlatformOperator).one()
    operator.is_active = False
    db.commit()

    with pytest.raises(PlatformOperatorRequired):
        set_platform_emergency_stop(
            db,
            operator.id,
            False,
            "Attempted unauthorized release",
        )

    assert db.query(PlatformEmergencyStopState).count() == 0
    assert db.query(PlatformEmergencyStopEvent).count() == 0


def test_active_operator_can_deactivate_and_audit(db):
    operator = db.query(PlatformOperator).one()

    state = set_platform_emergency_stop(
        db,
        operator.id,
        False,
        "Approved platform release",
    )

    assert state.id == PLATFORM_STOP_STATE_ID
    assert state.is_active is False
    assert is_platform_emergency_stop_active(db) is False

    events = db.query(PlatformEmergencyStopEvent).all()
    assert len(events) == 1
    assert events[0].event_type == "deactivated"
    assert events[0].operator_id == operator.id
    assert events[0].reason == "Approved platform release"


def test_operator_can_activate_and_reactivate_stop(db):
    operator = db.query(PlatformOperator).one()

    set_platform_emergency_stop(
        db, operator.id, False, "Initial approved release"
    )
    set_platform_emergency_stop(
        db, operator.id, True, "Critical platform safety incident"
    )

    assert is_platform_emergency_stop_active(db) is True
    assert db.query(PlatformEmergencyStopState).count() == 1

    events = (
        db.query(PlatformEmergencyStopEvent)
        .order_by(PlatformEmergencyStopEvent.created_at)
        .all()
    )
    assert len(events) == 2
    assert [event.event_type for event in events] == [
        "deactivated",
        "activated",
    ]


@pytest.mark.parametrize(
    "reason",
    ["", "  ", "bad", "x" * 1001, None],
)
def test_invalid_reason_is_rejected(db, reason):
    operator = db.query(PlatformOperator).one()

    with pytest.raises(InvalidPlatformStopReason):
        set_platform_emergency_stop(
            db, operator.id, False, reason
        )

    assert db.query(PlatformEmergencyStopState).count() == 0
    assert db.query(PlatformEmergencyStopEvent).count() == 0


def test_reason_is_trimmed_before_storage(db):
    operator = db.query(PlatformOperator).one()

    state = set_platform_emergency_stop(
        db,
        operator.id,
        False,
        "  Approved platform release  ",
    )

    assert state.reason == "Approved platform release"

    event = db.query(PlatformEmergencyStopEvent).one()
    assert event.reason == "Approved platform release"


def test_transitions_reuse_single_state_row(db):
    operator = db.query(PlatformOperator).one()

    set_platform_emergency_stop(
        db, operator.id, False, "Approved release"
    )
    set_platform_emergency_stop(
        db, operator.id, True, "Emergency activation"
    )
    set_platform_emergency_stop(
        db, operator.id, False, "Second approved release"
    )

    assert db.query(PlatformEmergencyStopState).count() == 1
    assert db.query(PlatformEmergencyStopEvent).count() == 3
    assert is_platform_emergency_stop_active(db) is False
