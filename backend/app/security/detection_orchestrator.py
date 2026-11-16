"""Orchestrate deterministic detection and platform finding persistence."""

from datetime import datetime
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.migrations import (
    ACTIVE_DEFENSE_MIGRATION_VERSION,
    PLATFORM_DETECTION_MIGRATION_VERSION,
    SECURITY_SIGNALS_MIGRATION_VERSION,
)
from app.database.session import SessionLocal
from app.security.detection_engine import (
    DetectionThresholds,
    detect_failed_login_patterns,
)
from app.security.finding_persistence import persist_detection_findings


REQUIRED_MIGRATIONS = frozenset(
    {
        ACTIVE_DEFENSE_MIGRATION_VERSION,
        SECURITY_SIGNALS_MIGRATION_VERSION,
        PLATFORM_DETECTION_MIGRATION_VERSION,
    }
)


class DetectionMigrationsUnavailable(RuntimeError):
    """Raised when required database migrations are missing or unreadable."""


def _verify_required_migrations(
    session_factory: Callable[[], Session],
) -> None:
    """Fail closed unless all required migrations are already recorded."""

    try:
        with session_factory() as db:
            result = db.execute(
                text(
                    """
                    SELECT version
                    FROM cyvanta_schema_migrations
                    WHERE version IN (
                        :active_defense,
                        :security_signals,
                        :platform_detection
                    )
                    """
                ),
                {
                    "active_defense": ACTIVE_DEFENSE_MIGRATION_VERSION,
                    "security_signals": SECURITY_SIGNALS_MIGRATION_VERSION,
                    "platform_detection": PLATFORM_DETECTION_MIGRATION_VERSION,
                },
            )

            installed = set(result.scalars().all())

    except Exception as exc:
        raise DetectionMigrationsUnavailable(
            "Unable to verify required detection migrations."
        ) from exc

    missing = REQUIRED_MIGRATIONS - installed

    if missing:
        raise DetectionMigrationsUnavailable(
            "Required detection migrations are missing."
        )


def run_detection_scan(
    session_factory: Callable[[], Session] = SessionLocal,
    now: datetime | None = None,
    thresholds: DetectionThresholds | None = None,
) -> dict:
    """
    Run one deterministic detection scan and persist its findings.

    Detection and persistence use separate short-lived database sessions.
    This function does not apply migrations or execute security actions.
    """

    _verify_required_migrations(session_factory)

    # Detection may open a read transaction. Close this session completely
    # before opening the clean session required by finding persistence.
    with session_factory() as detection_db:
        findings = detect_failed_login_patterns(
            db=detection_db,
            now=now,
            thresholds=thresholds,
        )

    # Persistence requires a fresh session with no active transaction.
    with session_factory() as persistence_db:
        persistence_summary = persist_detection_findings(
            db=persistence_db,
            findings=findings,
        )

    return {
        "detected": len(findings),
        **persistence_summary,
    }
