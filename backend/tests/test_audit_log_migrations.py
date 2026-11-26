import pytest

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.database.base import Base
from app import models  # noqa: F401
from app.database.migrations import (
    AUDIT_LOG_MIGRATION_VERSION,
    ensure_audit_log_migrations,
)


@pytest.fixture
def audit_migration_engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    try:
        yield engine
    finally:
        engine.dispose()


def test_audit_log_migration_is_idempotent(audit_migration_engine):
    ensure_audit_log_migrations(audit_migration_engine)
    ensure_audit_log_migrations(audit_migration_engine)

    with audit_migration_engine.connect() as connection:
        versions = connection.execute(
            text("""
                SELECT version
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {"version": AUDIT_LOG_MIGRATION_VERSION},
        ).scalars().all()

    assert versions == [AUDIT_LOG_MIGRATION_VERSION]


def test_audit_log_append_only_triggers_exist(audit_migration_engine):
    ensure_audit_log_migrations(audit_migration_engine)

    with audit_migration_engine.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                text("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'trigger'
                """)
            ).all()
        }

    assert "prevent_audit_logs_update" in names
    assert "prevent_audit_logs_delete" in names


def test_audit_log_rejects_update_and_delete(audit_migration_engine):
    ensure_audit_log_migrations(audit_migration_engine)

    with audit_migration_engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO audit_logs (
                    id, action, target_type, details, created_at
                )
                VALUES (
                    'audit-immutable-test',
                    'test.created',
                    'test',
                    '{}',
                    CURRENT_TIMESTAMP
                )
            """)
        )

    with pytest.raises(DBAPIError, match="append-only audit history"):
        with audit_migration_engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE audit_logs
                    SET action = 'test.modified'
                    WHERE id = 'audit-immutable-test'
                """)
            )

    with pytest.raises(DBAPIError, match="append-only audit history"):
        with audit_migration_engine.begin() as connection:
            connection.execute(
                text("""
                    DELETE FROM audit_logs
                    WHERE id = 'audit-immutable-test'
                """)
            )

    with audit_migration_engine.connect() as connection:
        record = connection.execute(
            text("""
                SELECT action
                FROM audit_logs
                WHERE id = 'audit-immutable-test'
            """)
        ).scalar_one()

    assert record == "test.created"


def test_audit_log_migration_preserves_existing_tables(audit_migration_engine):
    from sqlalchemy import inspect

    before = set(inspect(audit_migration_engine).get_table_names())

    ensure_audit_log_migrations(audit_migration_engine)

    after = set(inspect(audit_migration_engine).get_table_names())

    assert before.issubset(after)
    assert "audit_logs" in after
