
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from app.security.login_rate_limiter import consume_login_attempt


TEST_HMAC_KEY = "TEST_ONLY_CYVANTA_RATE_LIMIT_KEY_32_BYTES_MINIMUM"


@pytest.fixture
def rate_limit_engine(tmp_path):
    database_path = tmp_path / "rate_limit_cleanup_tests.sqlite"

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"timeout": 10},
    )

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE login_rate_limits (
                scope VARCHAR(30) NOT NULL,
                fingerprint VARCHAR(64) NOT NULL,
                window_started_at DATETIME NOT NULL,
                attempts INTEGER NOT NULL,
                PRIMARY KEY (scope, fingerprint)
            )
        """))

    yield engine
    engine.dispose()


def insert_bucket(
    engine,
    scope,
    fingerprint,
    started_at,
    attempts,
):
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
                    :scope,
                    :fingerprint,
                    :started_at,
                    :attempts
                )
            """),
            {
                "scope": scope,
                "fingerprint": fingerprint,
                "started_at": started_at.isoformat(sep=" "),
                "attempts": attempts,
            },
        )


def test_cleanup_removes_expired_buckets(rate_limit_engine):
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)

    insert_bucket(
        rate_limit_engine,
        "ip",
        "a" * 64,
        now - timedelta(minutes=16),
        3,
    )

    decision = consume_login_attempt(
        engine=rate_limit_engine,
        ip_address="192.0.2.70",
        account_identifier="cleanup@example.com",
        hmac_key=TEST_HMAC_KEY,
        now=now,
    )

    assert decision.allowed is True

    with rate_limit_engine.connect() as connection:
        expired_count = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM login_rate_limits
                WHERE fingerprint = :fingerprint
            """),
            {"fingerprint": "a" * 64},
        ).scalar_one()

    assert expired_count == 0


def test_cleanup_preserves_active_buckets(rate_limit_engine):
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)

    insert_bucket(
        rate_limit_engine,
        "ip",
        "b" * 64,
        now - timedelta(minutes=5),
        3,
    )

    decision = consume_login_attempt(
        engine=rate_limit_engine,
        ip_address="192.0.2.71",
        account_identifier="active@example.com",
        hmac_key=TEST_HMAC_KEY,
        now=now,
    )

    assert decision.allowed is True

    with rate_limit_engine.connect() as connection:
        active_row = connection.execute(
            text("""
                SELECT attempts
                FROM login_rate_limits
                WHERE scope = 'ip'
                  AND fingerprint = :fingerprint
            """),
            {"fingerprint": "b" * 64},
        ).scalar_one()

    assert active_row == 3


def test_cleanup_removes_expired_but_keeps_active_buckets(
    rate_limit_engine,
):
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)

    insert_bucket(
        rate_limit_engine,
        "ip",
        "c" * 64,
        now - timedelta(minutes=16),
        2,
    )

    insert_bucket(
        rate_limit_engine,
        "ip",
        "d" * 64,
        now - timedelta(minutes=5),
        4,
    )

    decision = consume_login_attempt(
        engine=rate_limit_engine,
        ip_address="192.0.2.72",
        account_identifier="mixed@example.com",
        hmac_key=TEST_HMAC_KEY,
        now=now,
    )

    assert decision.allowed is True

    with rate_limit_engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT fingerprint, attempts
                FROM login_rate_limits
                WHERE fingerprint IN (:expired, :active)
            """),
            {
                "expired": "c" * 64,
                "active": "d" * 64,
            },
        ).mappings().all()

    assert len(rows) == 1
    assert rows[0]["fingerprint"] == "d" * 64
    assert rows[0]["attempts"] == 4
