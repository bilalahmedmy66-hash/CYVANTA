
import pytest

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.migrations import (
    PLATFORM_DETECTION_MIGRATION_VERSION,
    ensure_platform_detection_migrations,
)
from app import models


@pytest.fixture
def migration_engine():
    engine = create_engine("sqlite:///:memory:")

    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()


def test_migration_installs_append_only_triggers(migration_engine):
    ensure_platform_detection_migrations(migration_engine)

    with migration_engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'trigger'
                """)
            )
        }

    assert (
        "prevent_platform_detection_finding_events_update"
        in triggers
    )
    assert (
        "prevent_platform_detection_finding_events_delete"
        in triggers
    )


def test_migration_records_version(migration_engine):
    ensure_platform_detection_migrations(migration_engine)

    with migration_engine.connect() as connection:
        versions = connection.execute(
            text("""
                SELECT version
                FROM cyvanta_schema_migrations
            """)
        ).scalars().all()

    assert PLATFORM_DETECTION_MIGRATION_VERSION in versions


def test_migration_is_safe_to_rerun(migration_engine):
    ensure_platform_detection_migrations(migration_engine)
    ensure_platform_detection_migrations(migration_engine)

    with migration_engine.connect() as connection:
        count = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {"version": PLATFORM_DETECTION_MIGRATION_VERSION},
        ).scalar_one()

    assert count == 1


def test_finding_events_cannot_be_updated(migration_engine):
    ensure_platform_detection_migrations(migration_engine)

    with migration_engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO platform_detection_findings (
                    id, rule_id, deduplication_key, severity,
                    status, title, description, evidence,
                    first_detected_at, last_detected_at,
                    occurrence_count, created_at, updated_at
                )
                VALUES (
                    'finding-1', 'AUTH_IP_BURST', 'dedup-1',
                    'high', 'open', 'Test finding', '',
                    '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """)
        )

        connection.execute(
            text("""
                INSERT INTO platform_detection_finding_events (
                    id, finding_id, event_type, reason,
                    details, created_at
                )
                VALUES (
                    'event-1', 'finding-1', 'detected',
                    'Test event', '{}', CURRENT_TIMESTAMP
                )
            """)
        )

    with pytest.raises(DBAPIError):
        with migration_engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE platform_detection_finding_events
                    SET reason = 'Modified'
                    WHERE id = 'event-1'
                """)
            )


def test_finding_events_cannot_be_deleted(migration_engine):
    ensure_platform_detection_migrations(migration_engine)

    with migration_engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO platform_detection_findings (
                    id, rule_id, deduplication_key, severity,
                    status, title, description, evidence,
                    first_detected_at, last_detected_at,
                    occurrence_count, created_at, updated_at
                )
                VALUES (
                    'finding-2', 'AUTH_IP_BURST', 'dedup-2',
                    'high', 'open', 'Test finding', '',
                    '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """)
        )

        connection.execute(
            text("""
                INSERT INTO platform_detection_finding_events (
                    id, finding_id, event_type, reason,
                    details, created_at
                )
                VALUES (
                    'event-2', 'finding-2', 'detected',
                    'Test event', '{}', CURRENT_TIMESTAMP
                )
            """)
        )

    with pytest.raises(DBAPIError):
        with migration_engine.begin() as connection:
            connection.execute(
                text("""
                    DELETE FROM platform_detection_finding_events
                    WHERE id = 'event-2'
                """)
            )


def test_finding_projection_remains_mutable(migration_engine):
    ensure_platform_detection_migrations(migration_engine)

    with migration_engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO platform_detection_findings (
                    id, rule_id, deduplication_key, severity,
                    status, title, description, evidence,
                    first_detected_at, last_detected_at,
                    occurrence_count, created_at, updated_at
                )
                VALUES (
                    'finding-3', 'AUTH_IP_BURST', 'dedup-3',
                    'high', 'open', 'Test finding', '',
                    '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """)
        )

        connection.execute(
            text("""
                UPDATE platform_detection_findings
                SET occurrence_count = 2
                WHERE id = 'finding-3'
            """)
        )

        count = connection.execute(
            text("""
                SELECT occurrence_count
                FROM platform_detection_findings
                WHERE id = 'finding-3'
            """)
        ).scalar_one()

    assert count == 2
