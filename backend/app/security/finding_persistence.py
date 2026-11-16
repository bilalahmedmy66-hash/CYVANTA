
"""Persist deterministic CYVANTA detection findings and audit events."""

import hashlib
import ipaddress
import json

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    PlatformDetectionFinding,
    PlatformDetectionFindingEvent,
    SecuritySignal,
)
from app.security.security_signals import FAILED_LOGIN_EVENT


SUPPORTED_RULES = {
    "AUTH_IP_BURST",
    "AUTH_ACCOUNT_BURST",
    "AUTH_DISTRIBUTED_ATTEMPT",
}


def _normalize_utc(value: datetime) -> datetime:
    """Normalize timestamps to UTC."""

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


def _get_finding_identity(finding) -> dict:
    """Build a stable identity for a supported detection rule."""

    evidence = finding.evidence or {}

    if finding.rule_id == "AUTH_IP_BURST":
        source_ip = _normalize_ip(evidence.get("source_ip"))

        if not source_ip:
            raise ValueError(
                "AUTH_IP_BURST requires a valid source IP."
            )

        return {"source_ip": source_ip}

    if finding.rule_id in {
        "AUTH_ACCOUNT_BURST",
        "AUTH_DISTRIBUTED_ATTEMPT",
    }:
        fingerprint = str(
            evidence.get("account_fingerprint") or ""
        ).strip()

        if not fingerprint:
            raise ValueError(
                f"{finding.rule_id} requires an account fingerprint."
            )

        return {"account_fingerprint": fingerprint}

    raise ValueError(
        f"Unsupported detection rule: {finding.rule_id}"
    )


def _build_deduplication_key(finding) -> str:
    """Create a stable SHA-256 finding identity."""

    identity = {
        "rule_id": finding.rule_id,
        "target": _get_finding_identity(finding),
    }

    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def _get_signal_ids(evidence: dict) -> list[str]:
    """Validate and normalize contributing security signal IDs."""

    signal_ids = evidence.get("signal_ids")

    if not isinstance(signal_ids, list) or not signal_ids:
        raise ValueError(
            "A detection finding must contain signal_ids."
        )

    normalized = []

    for signal_id in signal_ids:
        if not isinstance(signal_id, str):
            raise ValueError(
                "Every signal ID must be a string."
            )

        signal_id = signal_id.strip()

        if not signal_id:
            raise ValueError(
                "Signal IDs cannot be empty."
            )

        normalized.append(signal_id)

    return sorted(set(normalized))


def _validate_signal_evidence(
    db: Session,
    rule_id: str,
    identity: dict,
    signal_ids: list[str],
) -> None:
    """
    Verify every contributing ID against persisted failed-login signals.

    No caller-provided signal ID is trusted without database verification.
    """

    signals = (
        db.query(SecuritySignal)
        .filter(SecuritySignal.id.in_(signal_ids))
        .all()
    )

    signals_by_id = {
        signal.id: signal
        for signal in signals
    }

    missing_ids = set(signal_ids) - set(signals_by_id)

    if missing_ids:
        raise ValueError(
            "Finding contains security signal IDs that do not exist."
        )

    for signal in signals:

        if signal.event_type != FAILED_LOGIN_EVENT:
            raise ValueError(
                "Finding evidence contains an unsupported signal type."
            )

        if rule_id == "AUTH_IP_BURST":
            normalized_signal_ip = _normalize_ip(
                signal.source_ip
            )

            if normalized_signal_ip != identity["source_ip"]:
                raise ValueError(
                    "A security signal does not match the finding source IP."
                )

        elif rule_id in {
            "AUTH_ACCOUNT_BURST",
            "AUTH_DISTRIBUTED_ATTEMPT",
        }:
            if (
                signal.account_fingerprint
                != identity["account_fingerprint"]
            ):
                raise ValueError(
                    "A security signal does not match the account fingerprint."
                )

            if rule_id == "AUTH_DISTRIBUTED_ATTEMPT":
                if not _normalize_ip(signal.source_ip):
                    raise ValueError(
                        "Distributed findings require a valid source IP "
                        "for every signal."
                    )


def _create_lifecycle_event(
    db: Session,
    finding_id: str,
    event_type: str,
    reason: str,
    details: dict,
) -> None:
    """Append an immutable finding lifecycle event."""

    db.add(
        PlatformDetectionFindingEvent(
            finding_id=finding_id,
            event_type=event_type,
            reason=reason,
            details=details,
        )
    )


def persist_detection_findings(
    db: Session,
    findings: list,
) -> dict:
    """
    Persist detection findings and lifecycle events atomically.

    Requires a dedicated session with no active transaction.

    SQLite writers are serialized before finding lookups using
    BEGIN IMMEDIATE. Evidence is validated against persisted signals.
    """

    if db.in_transaction():
        raise RuntimeError(
            "Finding persistence requires a clean database session. "
            "Use a dedicated session with no active transaction."
        )

    if not isinstance(findings, list):
        raise TypeError("findings must be a list.")

    summary = {
        "created": 0,
        "updated": 0,
        "reopened": 0,
        "unchanged": 0,
        "processed": 0,
    }

    try:
        # Acquire the SQLite write lock before reading findings.
        connection = db.connection()

        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")

        for detection in findings:

            if detection.rule_id not in SUPPORTED_RULES:
                raise ValueError(
                    f"Unsupported detection rule: {detection.rule_id}"
                )

            incoming_evidence = dict(
                detection.evidence or {}
            )

            incoming_signal_ids = _get_signal_ids(
                incoming_evidence
            )

            identity = _get_finding_identity(detection)

            # Verify the actual persisted signals before trusting evidence.
            _validate_signal_evidence(
                db=db,
                rule_id=detection.rule_id,
                identity=identity,
                signal_ids=incoming_signal_ids,
            )

            deduplication_key = _build_deduplication_key(
                detection
            )

            detected_at = _normalize_utc(
                detection.detected_at
            )

            query = (
                db.query(PlatformDetectionFinding)
                .filter(
                    PlatformDetectionFinding.deduplication_key
                    == deduplication_key
                )
            )

            if connection.dialect.name != "sqlite":
                query = query.with_for_update()

            existing = query.one_or_none()

            # -------------------------------------------------
            # CREATE NEW FINDING
            # -------------------------------------------------

            if existing is None:

                stored_evidence = dict(incoming_evidence)

                stored_evidence["signal_ids"] = (
                    incoming_signal_ids
                )

                new_finding = PlatformDetectionFinding(
                    rule_id=detection.rule_id,
                    deduplication_key=deduplication_key,
                    severity=detection.severity,
                    status="open",
                    title=detection.title,
                    description=detection.description,
                    evidence=stored_evidence,
                    first_detected_at=detected_at,
                    last_detected_at=detected_at,
                    occurrence_count=len(incoming_signal_ids),
                )

                db.add(new_finding)
                db.flush()

                _create_lifecycle_event(
                    db=db,
                    finding_id=new_finding.id,
                    event_type="detected",
                    reason="New detection finding created.",
                    details={
                        "rule_id": detection.rule_id,
                        "severity": detection.severity,
                        "signal_ids": incoming_signal_ids,
                        "new_signal_count": len(incoming_signal_ids),
                    },
                )

                summary["created"] += 1
                summary["processed"] += 1

                continue

            # -------------------------------------------------
            # UPDATE EXISTING FINDING
            # -------------------------------------------------

            existing_evidence = dict(
                existing.evidence or {}
            )

            existing_signal_ids = set(
                existing_evidence.get("signal_ids", [])
            )

            incoming_signal_set = set(
                incoming_signal_ids
            )

            new_signal_ids = sorted(
                incoming_signal_set - existing_signal_ids
            )

            if not new_signal_ids:
                summary["unchanged"] += 1
                summary["processed"] += 1

                continue

            updated_signal_ids = sorted(
                existing_signal_ids | incoming_signal_set
            )

            updated_evidence = dict(existing_evidence)

            updated_evidence.update(incoming_evidence)

            updated_evidence["signal_ids"] = (
                updated_signal_ids
            )

            existing.evidence = updated_evidence
            existing.occurrence_count = len(updated_signal_ids)
            existing.last_detected_at = detected_at
            existing.severity = detection.severity
            existing.title = detection.title
            existing.description = detection.description

            was_reopened = existing.status != "open"

            if was_reopened:
                existing.status = "open"

            db.flush()

            # -------------------------------------------------
            # RECORD LIFECYCLE EVENT
            # -------------------------------------------------

            if was_reopened:

                _create_lifecycle_event(
                    db=db,
                    finding_id=existing.id,
                    event_type="reopened",
                    reason=(
                        "New security evidence was received "
                        "for a previously closed finding."
                    ),
                    details={
                        "rule_id": detection.rule_id,
                        "new_signal_ids": new_signal_ids,
                        "new_signal_count": len(new_signal_ids),
                        "total_signal_count": len(updated_signal_ids),
                    },
                )

                summary["reopened"] += 1

            else:

                _create_lifecycle_event(
                    db=db,
                    finding_id=existing.id,
                    event_type="evidence_added",
                    reason=(
                        "New security signals contributed "
                        "to an existing finding."
                    ),
                    details={
                        "rule_id": detection.rule_id,
                        "new_signal_ids": new_signal_ids,
                        "new_signal_count": len(new_signal_ids),
                        "total_signal_count": len(updated_signal_ids),
                    },
                )

                summary["updated"] += 1

            summary["processed"] += 1

        # Finding projection and lifecycle history commit together.
        db.commit()

        return summary

    except Exception:
        db.rollback()
        raise
