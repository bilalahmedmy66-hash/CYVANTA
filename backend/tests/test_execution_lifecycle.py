import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import ExecutionRecord
from app.action_engine.execution_lifecycle import transition_execution


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def create_execution(db, status="queued"):
    record = ExecutionRecord(
        action_request_id="action-test-001",
        organization_id="organization-test-001",
        status=status,
        result={"mode": "queued_only"},
        verified=False,
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return record


def test_queued_execution_can_transition_to_running(db_session):
    record = create_execution(db_session)

    updated = transition_execution(
        db_session,
        record.id,
        "running",
    )

    assert updated.status == "running"
    assert updated.started_at is not None
    assert updated.completed_at is None


def test_running_execution_can_transition_to_completed(db_session):
    record = create_execution(db_session, status="running")

    updated = transition_execution(
        db_session,
        record.id,
        "completed",
    )

    assert updated.status == "completed"
    assert updated.completed_at is not None


def test_running_execution_can_transition_to_failed(db_session):
    record = create_execution(db_session, status="running")

    updated = transition_execution(
        db_session,
        record.id,
        "failed",
    )

    assert updated.status == "failed"
    assert updated.completed_at is not None


def test_queued_execution_can_transition_to_cancelled(db_session):
    record = create_execution(db_session)

    updated = transition_execution(
        db_session,
        record.id,
        "cancelled",
    )

    assert updated.status == "cancelled"
    assert updated.started_at is None
    assert updated.completed_at is not None


@pytest.mark.parametrize(
    ("initial_status", "target_status"),
    [
        ("queued", "completed"),
        ("queued", "failed"),
        ("running", "queued"),
        ("completed", "running"),
        ("completed", "failed"),
        ("failed", "running"),
        ("failed", "completed"),
        ("cancelled", "queued"),
        ("cancelled", "running"),
    ],
)
def test_invalid_execution_transitions_are_rejected(
    db_session,
    initial_status,
    target_status,
):
    record = create_execution(db_session, status=initial_status)

    with pytest.raises(ValueError, match="Invalid execution transition"):
        transition_execution(
            db_session,
            record.id,
            target_status,
        )

    db_session.refresh(record)
    assert record.status == initial_status


def test_unknown_target_status_is_rejected(db_session):
    record = create_execution(db_session)

    with pytest.raises(ValueError, match="Unsupported execution status"):
        transition_execution(
            db_session,
            record.id,
            "paused",
        )

    db_session.refresh(record)
    assert record.status == "queued"


def test_missing_execution_is_rejected(db_session):
    with pytest.raises(ValueError, match="Execution record not found"):
        transition_execution(
            db_session,
            "missing-execution-id",
            "running",
        )
