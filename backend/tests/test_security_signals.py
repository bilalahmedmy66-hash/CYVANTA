import pytest

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.base import Base
from app.models import SecuritySignal
from app.security.security_signals import (
    FAILED_LOGIN_EVENT,
    create_account_fingerprint,
    record_failed_login_signal,
)


TEST_KEY = "TEST_ONLY_KEY_FOR_CYVANTA_SECURITY_SIGNALS_2026"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_fingerprint_is_generated():
    fingerprint = create_account_fingerprint(
        "user@example.com",
        TEST_KEY,
    )

    assert fingerprint is not None
    assert len(fingerprint) == 64


def test_fingerprint_normalizes_account_identifier():
    first = create_account_fingerprint(
        "User@Example.com",
        TEST_KEY,
    )
    second = create_account_fingerprint(
        " user@example.com ",
        TEST_KEY,
    )

    assert first == second


def test_missing_or_short_key_is_rejected():
    assert create_account_fingerprint(
        "user@example.com",
        None,
    ) is None

    assert create_account_fingerprint(
        "user@example.com",
        "short-key",
    ) is None


def test_empty_account_identifier_is_rejected():
    assert create_account_fingerprint(
        "   ",
        TEST_KEY,
    ) is None


def test_failed_login_signal_is_recorded(db_session):
    result = record_failed_login_signal(
        db=db_session,
        account_identifier="user@example.com",
        source_ip="127.0.0.1",
        hmac_key=TEST_KEY,
    )

    signal = db_session.execute(
        select(SecuritySignal)
    ).scalar_one()

    assert result is True
    assert signal.event_type == FAILED_LOGIN_EVENT
    assert signal.account_fingerprint is not None
    assert len(signal.account_fingerprint) == 64
    assert signal.source_ip == "127.0.0.1"
    assert "user@example.com" not in str(signal.details)


def test_signal_is_recorded_without_fingerprint_when_key_missing(
    db_session,
):
    result = record_failed_login_signal(
        db=db_session,
        account_identifier="user@example.com",
        source_ip="127.0.0.1",
        hmac_key=None,
    )

    signal = db_session.execute(
        select(SecuritySignal)
    ).scalar_one()

    assert result is True
    assert signal.event_type == FAILED_LOGIN_EVENT
    assert signal.account_fingerprint is None


def test_database_error_returns_false_and_rolls_back(
    db_session,
    monkeypatch,
):
    def failing_commit():
        raise SQLAlchemyError("Simulated database failure")

    monkeypatch.setattr(db_session, "commit", failing_commit)

    result = record_failed_login_signal(
        db=db_session,
        account_identifier="user@example.com",
        source_ip="127.0.0.1",
        hmac_key=TEST_KEY,
    )

    assert result is False

    signals = db_session.execute(
        select(SecuritySignal)
    ).scalars().all()

    assert signals == []
