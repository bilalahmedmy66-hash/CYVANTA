
"""Deterministic detection engine for trusted failed-login signals."""

import ipaddress
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import SecuritySignal
from app.security.security_signals import FAILED_LOGIN_EVENT


@dataclass(frozen=True)
class DetectionThresholds:
    """Initial development thresholds for failed-login detection."""

    ip_burst_attempts: int = 10
    ip_burst_minutes: int = 5

    account_burst_attempts: int = 10
    account_burst_minutes: int = 5

    distributed_ip_count: int = 5
    distributed_minutes: int = 10


@dataclass(frozen=True)
class DetectionFinding:
    """An in-memory, read-only platform security finding."""

    rule_id: str
    severity: str
    title: str
    description: str
    detected_at: datetime
    evidence: dict


def _normalize_utc(value: datetime) -> datetime:
    """Treat naive SQLite timestamps as UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _normalize_ip(value: str | None) -> str | None:
    """Validate and normalize an IPv4 or IPv6 address."""

    if not isinstance(value, str):
        return None

    candidate = value.strip()

    if not candidate:
        return None

    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _validate_thresholds(thresholds: DetectionThresholds) -> None:
    """Require positive integer detection thresholds."""

    required_values = (
        thresholds.ip_burst_attempts,
        thresholds.ip_burst_minutes,
        thresholds.account_burst_attempts,
        thresholds.account_burst_minutes,
        thresholds.distributed_ip_count,
        thresholds.distributed_minutes,
    )

    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        for value in required_values
    ):
        raise ValueError(
            "Detection thresholds must be positive integers."
        )


def detect_failed_login_patterns(
    db: Session,
    now: datetime | None = None,
    thresholds: DetectionThresholds | None = None,
) -> list[DetectionFinding]:
    """
    Analyse trusted failed-login signals.

    Detection rules:

    1. AUTH_IP_BURST
       Multiple failed logins from one valid source IP.

    2. AUTH_ACCOUNT_BURST
       Multiple failed logins against one account fingerprint.

    3. AUTH_DISTRIBUTED_ATTEMPT
       One account fingerprint targeted from multiple valid source IPs.

    This function:
    - Only reads SecuritySignal records.
    - Only loads signals within the maximum relevant time window.
    - Does not modify security signals.
    - Does not persist findings.
    - Does not execute containment actions.
    - Does not contact source IP addresses.
    """

    thresholds = thresholds or DetectionThresholds()
    _validate_thresholds(thresholds)

    current_time = _normalize_utc(
        now or datetime.now(timezone.utc)
    )

    earliest_cutoff = current_time - timedelta(
        minutes=max(
            thresholds.ip_burst_minutes,
            thresholds.account_burst_minutes,
            thresholds.distributed_minutes,
        )
    )

    signals = (
        db.query(SecuritySignal)
        .filter(
            SecuritySignal.event_type == FAILED_LOGIN_EVENT,
            SecuritySignal.created_at >= earliest_cutoff,
            SecuritySignal.created_at <= current_time,
        )
        .all()
    )

    valid_signals = []

    for signal in signals:
        timestamp = _normalize_utc(signal.created_at)

        if not earliest_cutoff <= timestamp <= current_time:
            continue

        valid_signals.append((signal, timestamp))

    findings = []

    # =====================================================
    # RULE 1: AUTH_IP_BURST
    # =====================================================

    ip_groups = defaultdict(list)

    for signal, timestamp in valid_signals:
        ip = _normalize_ip(signal.source_ip)

        if ip:
            ip_groups[ip].append((signal, timestamp))

    ip_cutoff = current_time - timedelta(
        minutes=thresholds.ip_burst_minutes
    )

    for ip, entries in ip_groups.items():
        recent = [
            (signal, timestamp)
            for signal, timestamp in entries
            if timestamp >= ip_cutoff
        ]

        if len(recent) >= thresholds.ip_burst_attempts:
            findings.append(
                DetectionFinding(
                    rule_id="AUTH_IP_BURST",
                    severity="high",
                    title="Repeated failed logins from one IP",
                    description=(
                        f"{len(recent)} failed login attempts "
                        f"were recorded from one source IP within "
                        f"{thresholds.ip_burst_minutes} minutes."
                    ),
                    detected_at=current_time,
                    evidence={
                        "source_ip": ip,
                        "attempt_count": len(recent),
                        "window_minutes": thresholds.ip_burst_minutes,
                        "signal_ids": [
                            signal.id
                            for signal, timestamp in recent
                        ],
                    },
                )
            )

    # =====================================================
    # RULE 2: AUTH_ACCOUNT_BURST
    # =====================================================

    account_groups = defaultdict(list)

    for signal, timestamp in valid_signals:
        fingerprint = signal.account_fingerprint

        if isinstance(fingerprint, str) and fingerprint.strip():
            account_groups[fingerprint].append(
                (signal, timestamp)
            )

    account_cutoff = current_time - timedelta(
        minutes=thresholds.account_burst_minutes
    )

    for fingerprint, entries in account_groups.items():
        recent = [
            (signal, timestamp)
            for signal, timestamp in entries
            if timestamp >= account_cutoff
        ]

        if len(recent) >= thresholds.account_burst_attempts:
            findings.append(
                DetectionFinding(
                    rule_id="AUTH_ACCOUNT_BURST",
                    severity="high",
                    title="Repeated failed logins against one account",
                    description=(
                        f"{len(recent)} failed login attempts "
                        f"targeted one account fingerprint within "
                        f"{thresholds.account_burst_minutes} minutes."
                    ),
                    detected_at=current_time,
                    evidence={
                        "account_fingerprint": fingerprint,
                        "attempt_count": len(recent),
                        "window_minutes": thresholds.account_burst_minutes,
                        "signal_ids": [
                            signal.id
                            for signal, timestamp in recent
                        ],
                    },
                )
            )

    # =====================================================
    # RULE 3: AUTH_DISTRIBUTED_ATTEMPT
    # =====================================================

    distributed_groups = defaultdict(set)
    distributed_entries = defaultdict(list)

    distributed_cutoff = current_time - timedelta(
        minutes=thresholds.distributed_minutes
    )

    for signal, timestamp in valid_signals:
        fingerprint = signal.account_fingerprint
        ip = _normalize_ip(signal.source_ip)

        if (
            isinstance(fingerprint, str)
            and fingerprint.strip()
            and ip
            and timestamp >= distributed_cutoff
        ):
            distributed_groups[fingerprint].add(ip)
            distributed_entries[fingerprint].append(
                (signal, timestamp)
            )

    for fingerprint, source_ips in distributed_groups.items():
        entries = distributed_entries[fingerprint]

        if len(source_ips) >= thresholds.distributed_ip_count:
            findings.append(
                DetectionFinding(
                    rule_id="AUTH_DISTRIBUTED_ATTEMPT",
                    severity="high",
                    title="Distributed failed-login activity",
                    description=(
                        f"One account fingerprint was targeted "
                        f"from {len(source_ips)} distinct source IPs "
                        f"within {thresholds.distributed_minutes} minutes."
                    ),
                    detected_at=current_time,
                    evidence={
                        "account_fingerprint": fingerprint,
                        "distinct_source_ips": len(source_ips),
                        "attempt_count": len(entries),
                        "window_minutes": thresholds.distributed_minutes,
                        "signal_ids": [
                            signal.id
                            for signal, timestamp in entries
                        ],
                    },
                )
            )

    return findings
