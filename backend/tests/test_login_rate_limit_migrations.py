
import pytest

from sqlalchemy import create_engine, inspect, text

from app.database.migrations import (
    LOGIN_RATE_LIMIT_MIGRATION_VERSION,
    ensure_login_rate_limit_migrations,
)


def test_migration_creates_table_and_records_version():
    engine = create_engine("sqlite:///:memory:")

    try:
        ensure_login_rate_limit_migrations(engine)

        inspector = inspect(engine)

        assert "login_rate_limits" in inspector.get_table_names()

        columns = {
            column["name"]
            for column in inspector.get_columns("login_rate_limits")
        }

        assert columns == {
            "scope",
            "fingerprint",
            "window_started_at",
            "attempts",
        }

        with engine.connect() as connection:
            version = connection.execute(
                text("""
                    SELECT version
                    FROM cyvanta_schema_migrations
                    WHERE version = :version
                """),
                {"version": LOGIN_RATE_LIMIT_MIGRATION_VERSION},
            ).scalar_one()

        assert version == LOGIN_RATE_LIMIT_MIGRATION_VERSION

    finally:
        engine.dispose()


def test_migration_is_idempotent():
    engine = create_engine("sqlite:///:memory:")

    try:
        ensure_login_rate_limit_migrations(engine)
        ensure_login_rate_limit_migrations(engine)

        with engine.connect() as connection:
            count = connection.execute(
                text("""
                    SELECT COUNT(*)
                    FROM cyvanta_schema_migrations
                    WHERE version = :version
                """),
                {"version": LOGIN_RATE_LIMIT_MIGRATION_VERSION},
            ).scalar_one()

        assert count == 1

    finally:
        engine.dispose()


def test_migration_preserves_existing_rate_limit_data():
    engine = create_engine("sqlite:///:memory:")

    try:
        ensure_login_rate_limit_migrations(engine)

        with engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO login_rate_limits (
                        scope,
                        fingerprint,
                        window_started_at,
                        attempts
                    )
                    VALUES (
                        'ip',
                        'a' || printf('%063d', 0),
                        '2026-11-18 12:00:00',
                        3
                    )
                """)
            )

        ensure_login_rate_limit_migrations(engine)

        with engine.connect() as connection:
            row = connection.execute(
                text("""
                    SELECT scope, fingerprint, attempts
                    FROM login_rate_limits
                """)
            ).mappings().one()

        assert row["scope"] == "ip"
        assert len(row["fingerprint"]) == 64
        assert row["attempts"] == 3

    finally:
        engine.dispose()


def test_migration_rejects_invalid_existing_table_schema():
    engine = create_engine("sqlite:///:memory:")

    try:
        with engine.begin() as connection:
            connection.execute(
                text("""
                    CREATE TABLE login_rate_limits (
                        scope VARCHAR(30) PRIMARY KEY
                    )
                """)
            )

        with pytest.raises(
            RuntimeError,
            match="invalid schema",
        ):
            ensure_login_rate_limit_migrations(engine)

    finally:
        engine.dispose()


def test_rate_limit_table_rejects_zero_attempts():
    engine = create_engine("sqlite:///:memory:")

    try:
        ensure_login_rate_limit_migrations(engine)

        with pytest.raises(Exception):
            with engine.begin() as connection:
                connection.execute(
                    text("""
                        INSERT INTO login_rate_limits (
                            scope,
                            fingerprint,
                            window_started_at,
                            attempts
                        )
                        VALUES (
                            'ip',
                            'b' || printf('%063d', 0),
                            CURRENT_TIMESTAMP,
                            0
                        )
                    """)
                )

    finally:
        engine.dispose()
