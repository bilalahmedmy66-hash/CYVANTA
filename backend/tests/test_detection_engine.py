
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import SecuritySignal
from app.security.detection_engine import (
    DetectionThresholds,
    detect_failed_login_patterns,
)
from app.security.security_signals import FAILED_LOGIN_EVENT


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

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def fixed_now():
    return datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def add_signal(
    db,
    created_at,
    source_ip="192.0.2.10",
    fingerprint="test-fingerprint",
    event_type=FAILED_LOGIN_EVENT,
):
    signal = SecuritySignal(
        event_type=event_type,
        account_fingerprint=fingerprint,
        source_ip=source_ip,
        details={"signal_source": "authentication"},
        created_at=created_at,
    )
    db.add(signal)
    db.flush()
    return signal


def test_ip_burst_detected(db, fixed_now):
    for _ in range(10):
        add_signal(db, fixed_now - timedelta(minutes=2))

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert any(
        item.rule_id == "AUTH_IP_BURST"
        for item in findings
    )


def test_ip_burst_below_threshold_not_detected(db, fixed_now):
    for _ in range(9):
        add_signal(db, fixed_now - timedelta(minutes=2))

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert not any(
        item.rule_id == "AUTH_IP_BURST"
        for item in findings
    )


def test_account_burst_detected(db, fixed_now):
    for _ in range(10):
        add_signal(
            db,
            fixed_now - timedelta(minutes=2),
            source_ip=None,
            fingerprint="account-123",
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert any(
        item.rule_id == "AUTH_ACCOUNT_BURST"
        for item in findings
    )


def test_account_rule_skips_missing_fingerprints(db, fixed_now):
    for _ in range(15):
        add_signal(
            db,
            fixed_now - timedelta(minutes=2),
            fingerprint=None,
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert not any(
        item.rule_id == "AUTH_ACCOUNT_BURST"
        for item in findings
    )


def test_distributed_attempt_detected(db, fixed_now):
    for index in range(5):
        add_signal(
            db,
            fixed_now - timedelta(minutes=3),
            source_ip=f"192.0.2.{index + 1}",
            fingerprint="shared-account",
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert any(
        item.rule_id == "AUTH_DISTRIBUTED_ATTEMPT"
        for item in findings
    )


def test_distributed_attempt_below_ip_threshold(db, fixed_now):
    for index in range(4):
        add_signal(
            db,
            fixed_now - timedelta(minutes=3),
            source_ip=f"192.0.2.{index + 1}",
            fingerprint="shared-account",
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert not any(
        item.rule_id == "AUTH_DISTRIBUTED_ATTEMPT"
        for item in findings
    )


def test_old_signals_are_ignored(db, fixed_now):
    for _ in range(10):
        add_signal(
            db,
            fixed_now - timedelta(minutes=6),
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert not any(
        item.rule_id == "AUTH_IP_BURST"
        for item in findings
    )


def test_future_signals_are_ignored(db, fixed_now):
    for _ in range(10):
        add_signal(
            db,
            fixed_now + timedelta(minutes=1),
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert findings == []


def test_other_event_types_are_ignored(db, fixed_now):
    for _ in range(10):
        add_signal(
            db,
            fixed_now - timedelta(minutes=1),
            event_type="some.other.event",
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert findings == []


def test_invalid_thresholds_are_rejected(db, fixed_now):
    thresholds = DetectionThresholds(
        ip_burst_attempts=0,
    )

    with pytest.raises(ValueError):
        detect_failed_login_patterns(
            db,
            now=fixed_now,
            thresholds=thresholds,
        )


def test_detection_does_not_modify_signals(db, fixed_now):
    for _ in range(10):
        add_signal(db, fixed_now - timedelta(minutes=2))

    before_count = db.query(SecuritySignal).count()

    detect_failed_login_patterns(db, now=fixed_now)

    after_count = db.query(SecuritySignal).count()

    assert before_count == after_count == 10

# =========================================================
# ADDITIONAL DETECTION REGRESSION TESTS
# =========================================================

def test_signal_exactly_at_window_boundary_is_included(db, fixed_now):
    for _ in range(10):
        add_signal(
            db,
            fixed_now - timedelta(minutes=5),
            source_ip="192.0.2.20",
            fingerprint=None,
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert any(
        item.rule_id == "AUTH_IP_BURST"
        for item in findings
    )


def test_separate_accounts_are_not_combined(db, fixed_now):
    for index in range(5):
        add_signal(
            db,
            fixed_now - timedelta(minutes=2),
            source_ip=None,
            fingerprint="account-A",
        )
        add_signal(
            db,
            fixed_now - timedelta(minutes=2),
            source_ip=None,
            fingerprint="account-B",
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert not any(
        item.rule_id == "AUTH_ACCOUNT_BURST"
        for item in findings
    )


def test_repeated_attempts_from_one_ip_do_not_trigger_distributed_rule(
    db,
    fixed_now,
):
    for _ in range(10):
        add_signal(
            db,
            fixed_now - timedelta(minutes=2),
            source_ip="192.0.2.30",
            fingerprint="shared-account",
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert not any(
        item.rule_id == "AUTH_DISTRIBUTED_ATTEMPT"
        for item in findings
    )


def test_invalid_ips_are_excluded_from_ip_detection(db, fixed_now):
    for _ in range(10):
        add_signal(
            db,
            fixed_now - timedelta(minutes=2),
            source_ip="not-a-valid-ip",
            fingerprint=None,
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert not any(
        item.rule_id == "AUTH_IP_BURST"
        for item in findings
    )


def test_ipv6_addresses_are_normalized_for_ip_detection(db, fixed_now):
    for _ in range(10):
        add_signal(
            db,
            fixed_now - timedelta(minutes=2),
            source_ip="2001:0db8:0000:0000:0000:0000:0000:0001",
            fingerprint=None,
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    ip_finding = next(
        (
            item
            for item in findings
            if item.rule_id == "AUTH_IP_BURST"
        ),
        None,
    )

    assert ip_finding is not None
    assert ip_finding.evidence["source_ip"] == "2001:db8::1"


def test_missing_source_ips_do_not_trigger_ip_detection(db, fixed_now):
    for _ in range(10):
        add_signal(
            db,
            fixed_now - timedelta(minutes=2),
            source_ip=None,
            fingerprint="account-without-ip",
        )

    findings = detect_failed_login_patterns(db, now=fixed_now)

    assert not any(
        item.rule_id == "AUTH_IP_BURST"
        for item in findings
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("ip_burst_attempts", 3.5),
        ("ip_burst_attempts", "10"),
        ("ip_burst_attempts", True),
        ("account_burst_minutes", 2.5),
        ("distributed_ip_count", False),
    ],
)
def test_invalid_threshold_types_are_rejected(
    db,
    fixed_now,
    field,
    value,
):
    thresholds = DetectionThresholds(**{field: value})

    with pytest.raises(ValueError):
        detect_failed_login_patterns(
            db,
            now=fixed_now,
            thresholds=thresholds,
        )


def test_naive_now_is_interpreted_as_utc(db):
    naive_now = datetime(2026, 11, 9, 12, 0)

    for _ in range(10):
        add_signal(
            db,
            datetime(2026, 11, 9, 11, 58),
            source_ip="192.0.2.40",
            fingerprint=None,
        )

    findings = detect_failed_login_patterns(db, now=naive_now)

    assert any(
        item.rule_id == "AUTH_IP_BURST"
        for item in findings
    )
