from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.database.base import Base
from app import models
from app.database.migrations import (
    SIMULATION_DISPATCH_MIGRATION_VERSION,
    ensure_simulation_dispatch_migrations,
)


def create_test_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_simulation_migration_is_idempotent():
    engine = create_test_engine()

    ensure_simulation_dispatch_migrations(engine)
    ensure_simulation_dispatch_migrations(engine)

    with engine.connect() as connection:
        versions = connection.execute(
            text("""
                SELECT version
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {"version": SIMULATION_DISPATCH_MIGRATION_VERSION},
        ).scalars().all()

    assert versions == [SIMULATION_DISPATCH_MIGRATION_VERSION]
    engine.dispose()


def test_simulation_event_append_only_triggers_exist():
    engine = create_test_engine()
    ensure_simulation_dispatch_migrations(engine)

    with engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'trigger'
                """)
            ).all()
        }

    assert "prevent_simulation_dispatch_events_update" in triggers
    assert "prevent_simulation_dispatch_events_delete" in triggers
    engine.dispose()


def test_simulation_event_cannot_be_updated_or_deleted():
    engine = create_test_engine()
    ensure_simulation_dispatch_migrations(engine)

    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO simulation_dispatch_events (
                    id, dispatch_id, organization_id,
                    event_type, worker_id, details, created_at
                )
                VALUES (
                    'event-test', 'dispatch-test', 'org-test',
                    'simulation_created', 'worker-test',
                    '{}', CURRENT_TIMESTAMP
                )
            """)
        )

    try:
        with engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE simulation_dispatch_events
                    SET event_type = 'tampered'
                    WHERE id = 'event-test'
                """)
            )
        raise AssertionError("Update unexpectedly succeeded.")
    except DBAPIError as exc:
        assert "simulation dispatch history cannot be updated" in str(exc)

    try:
        with engine.begin() as connection:
            connection.execute(
                text("""
                    DELETE FROM simulation_dispatch_events
                    WHERE id = 'event-test'
                """)
            )
        raise AssertionError("Delete unexpectedly succeeded.")
    except DBAPIError as exc:
        assert "simulation dispatch history cannot be deleted" in str(exc)

    engine.dispose()


def test_simulation_migration_requires_both_tables():
    engine = create_engine("sqlite:///:memory:")

    try:
        ensure_simulation_dispatch_migrations(engine)
        raise AssertionError("Migration unexpectedly succeeded.")
    except RuntimeError as exc:
        assert "Missing simulation dispatch tables" in str(exc)

    engine.dispose()
