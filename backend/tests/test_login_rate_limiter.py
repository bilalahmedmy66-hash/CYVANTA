import pytest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text

from app.security.login_rate_limiter import (
    consume_login_attempt,
    RateLimitUnavailable,
)


TEST_HMAC_KEY = "TEST_ONLY_CYVANTA_RATE_LIMIT_KEY_32_BYTES_MINIMUM"


@pytest.fixture
def rate_limit_engine(tmp_path):
    database_path = tmp_path / "rate_limit_tests.sqlite"
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


def attempt(engine, ip="192.0.2.10", email="user@example.com"):
    return consume_login_attempt(
        engine=engine,
        ip_address=ip,
        account_identifier=email,
        hmac_key=TEST_HMAC_KEY,
    )


def test_requests_below_limits_are_allowed(rate_limit_engine):
    for _ in range(5):
        decision = attempt(rate_limit_engine)

        assert decision.allowed is True


def test_pair_limit_blocks_sixth_request(rate_limit_engine):
    decisions = [
        attempt(rate_limit_engine)
        for _ in range(6)
    ]

    assert all(item.allowed for item in decisions[:5])
    assert decisions[5].allowed is False
    assert decisions[5].retry_after > 0


def test_different_ips_have_independent_pair_limits(rate_limit_engine):
    for _ in range(5):
        assert attempt(rate_limit_engine, ip="192.0.2.10").allowed

    other_ip = attempt(rate_limit_engine, ip="192.0.2.11")

    assert other_ip.allowed is True


def test_different_accounts_have_independent_pair_limits(rate_limit_engine):
    for _ in range(5):
        assert attempt(
            rate_limit_engine,
            email="first@example.com",
        ).allowed

    other_account = attempt(
        rate_limit_engine,
        email="second@example.com",
    )

    assert other_account.allowed is True


def test_expired_window_resets(rate_limit_engine):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for _ in range(5):
        decision = consume_login_attempt(
            engine=rate_limit_engine,
            ip_address="192.0.2.20",
            account_identifier="window@example.com",
            hmac_key=TEST_HMAC_KEY,
            now=start,
        )
        assert decision.allowed

    after_window = consume_login_attempt(
        engine=rate_limit_engine,
        ip_address="192.0.2.20",
        account_identifier="window@example.com",
        hmac_key=TEST_HMAC_KEY,
        now=start + timedelta(minutes=16),
    )

    assert after_window.allowed is True


def test_missing_hmac_key_fails_closed(rate_limit_engine):
    with pytest.raises(RateLimitUnavailable):
        consume_login_attempt(
            engine=rate_limit_engine,
            ip_address="192.0.2.30",
            account_identifier="private@example.com",
            hmac_key=None,
        )


def test_raw_identifiers_are_not_stored(rate_limit_engine):
    attempt(
        rate_limit_engine,
        ip="192.0.2.40",
        email="private@example.com",
    )

    with rate_limit_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT fingerprint FROM login_rate_limits")
        ).scalars().all()

    assert rows
    assert all("private@example.com" not in value for value in rows)
    assert all("192.0.2.40" not in value for value in rows)


def test_concurrent_requests_cannot_bypass_pair_limit(rate_limit_engine):
    def make_attempt(_):
        return attempt(
            rate_limit_engine,
            ip="192.0.2.50",
            email="concurrent@example.com",
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        decisions = list(executor.map(make_attempt, range(10)))

    allowed = sum(item.allowed for item in decisions)

    assert allowed == 5
    assert sum(not item.allowed for item in decisions) == 5


def test_ip_limit_blocks_eleventh_request(rate_limit_engine):
    decisions = [
        attempt(
            rate_limit_engine,
            ip="192.0.2.60",
            email=f"user-{index}@example.com",
        )
        for index in range(11)
    ]

    assert all(item.allowed for item in decisions[:10])
    assert decisions[10].allowed is False
    assert decisions[10].retry_after > 0


def test_database_failure_fails_closed(rate_limit_engine, monkeypatch):
    def fail_begin():
        raise OSError("Simulated database outage")

    monkeypatch.setattr(rate_limit_engine, "begin", fail_begin)

    with pytest.raises(RateLimitUnavailable):
        attempt(rate_limit_engine)

