from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.migrations import (
    ensure_active_defense_migrations,
    ensure_security_signals_migrations,
    ensure_platform_detection_migrations,
)
from app.models import (
    PlatformDetectionFinding,
    SecuritySignal,
)
from app.security.detection_engine import DetectionThresholds
from app.security.detection_orchestrator import (
    DetectionMigrationsUnavailable,
    run_detection_scan,
)
from app.security.security_signals import FAILED_LOGIN_EVENT


@pytest.fixture
def isolated_database():
    """Create a temporary in-memory database with required migrations."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    ensure_active_defense_migrations(engine)
    ensure_security_signals_migrations(engine)
    ensure_platform_detection_migrations(engine)

    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    try:
        yield engine, testing_session
    finally:
        engine.dispose()


@pytest.fixture
def fixed_now():
    return datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def seed_failed_logins(
    session_factory,
    fixed_now,
    count=10,
    source_ip="192.0.2.10",
):
    """Create trusted failed-login signals for an isolated test."""

    with session_factory() as db:
        for index in range(count):
            db.add(
                SecuritySignal(
                    event_type=FAILED_LOGIN_EVENT,
                    account_fingerprint=f"fingerprint-{index}",
                    source_ip=source_ip,
                    details={"signal_source": "test"},
                    created_at=fixed_now - timedelta(minutes=2),
                )
            )

        db.commit()


def test_missing_migrations_fail_closed(isolated_database):
    engine, session_factory = isolated_database

    # Use a separate schema without migration records.
    missing_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=missing_engine)

    missing_session_factory = sessionmaker(
        bind=missing_engine,
        autoflush=False,
        autocommit=False,
    )

    try:
        with pytest.raises(DetectionMigrationsUnavailable):
            run_detection_scan(
                session_factory=missing_session_factory,
            )
    finally:
        missing_engine.dispose()


def test_empty_database_returns_zero_findings(isolated_database, fixed_now):
    _, session_factory = isolated_database

    result = run_detection_scan(
        session_factory=session_factory,
        now=fixed_now,
    )

    assert result == {
        "detected": 0,
        "created": 0,
        "updated": 0,
        "reopened": 0,
        "unchanged": 0,
        "processed": 0,
    }


def test_scan_detects_and_persists_ip_burst(
    isolated_database,
    fixed_now,
):
    _, session_factory = isolated_database

    seed_failed_logins(
        session_factory=session_factory,
        fixed_now=fixed_now,
        count=10,
    )

    result = run_detection_scan(
        session_factory=session_factory,
        now=fixed_now,
    )

    assert result["detected"] >= 1
    assert result["created"] >= 1
    assert result["processed"] >= 1

    with session_factory() as db:
        finding_count = (
            db.query(func.count(PlatformDetectionFinding.id))
            .scalar()
        )

    assert finding_count >= 1


def test_repeated_scan_does_not_duplicate_findings(
    isolated_database,
    fixed_now,
):
    _, session_factory = isolated_database

    seed_failed_logins(
        session_factory=session_factory,
        fixed_now=fixed_now,
        count=10,
    )

    first_result = run_detection_scan(
        session_factory=session_factory,
        now=fixed_now,
    )

    second_result = run_detection_scan(
        session_factory=session_factory,
        now=fixed_now,
    )

    assert first_result["created"] >= 1
    assert second_result["created"] == 0
    assert second_result["unchanged"] >= 1

    with session_factory() as db:
        finding_count = (
            db.query(func.count(PlatformDetectionFinding.id))
            .scalar()
        )

    assert finding_count == first_result["created"]


def test_detection_and_persistence_use_separate_sessions(
    isolated_database,
    fixed_now,
):
    _, base_session_factory = isolated_database
    created_sessions = []

    def tracking_session_factory():
        session = base_session_factory()
        session.was_closed = False

        original_close = session.close

        def tracked_close():
            session.was_closed = True
            original_close()

        session.close = tracked_close
        created_sessions.append(session)

        return session

    run_detection_scan(
        session_factory=tracking_session_factory,
        now=fixed_now,
    )

    # Migration verification, detection, and persistence
    # must use three separate sessions.
    assert len(created_sessions) == 3
    assert len({id(session) for session in created_sessions}) == 3

    # Every session must be closed after its operation.
    assert all(session.was_closed for session in created_sessions)

    # No session should retain an active transaction.
    assert all(
        not session.in_transaction()
        for session in created_sessions
    )


def test_detection_thresholds_can_be_supplied(
    isolated_database,
    fixed_now,
):
    _, session_factory = isolated_database

    seed_failed_logins(
        session_factory=session_factory,
        fixed_now=fixed_now,
        count=3,
    )

    thresholds = DetectionThresholds(
        ip_burst_attempts=3,
        ip_burst_minutes=5,
        account_burst_attempts=100,
        account_burst_minutes=5,
        distributed_ip_count=5,
        distributed_minutes=10,
    )

    result = run_detection_scan(
        session_factory=session_factory,
        now=fixed_now,
        thresholds=thresholds,
    )

    assert result["detected"] >= 1
    assert result["created"] >= 1
