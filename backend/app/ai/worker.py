"""Single-process CYVANTA advisory AI job worker.

Run from backend with:
    .\\.venv\\Scripts\\python.exe -m app.ai.worker

Development deployment: run exactly one worker process.
"""
import logging
import time
from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.ai.service import (
    AIConfigurationError,
    AIProviderError,
    AIProviderQuotaExceeded,
    AIProviderUnavailable,
    analyze_with_gemini,
)
from app.database.session import SessionLocal
from app.models import AIAnalysisJob, utc_now

logger = logging.getLogger("cyvanta.ai.worker")
POLL_INTERVAL_SECONDS = 3
MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (30, 120)


def retry_delay(attempt_number: int) -> int | None:
    """Return bounded retry delay after attempt 1 or 2; None means terminal."""
    if attempt_number < 1 or attempt_number >= MAX_ATTEMPTS:
        return None
    return RETRY_DELAYS_SECONDS[attempt_number - 1]


def recover_interrupted_jobs(db: Session) -> int:
    """Recover interrupted jobs without exceeding the configured attempt limit."""
    now = utc_now()
    recoverable = db.execute(
        update(AIAnalysisJob)
        .where(
            AIAnalysisJob.status == "processing",
            AIAnalysisJob.attempts < MAX_ATTEMPTS,
        )
        .values(
            status="queued",
            started_at=None,
            next_retry_at=None,
            updated_at=now,
            error_code="WORKER_RESTART_RECOVERY",
        )
    )
    exhausted = db.execute(
        update(AIAnalysisJob)
        .where(
            AIAnalysisJob.status == "processing",
            AIAnalysisJob.attempts >= MAX_ATTEMPTS,
        )
        .values(
            status="failed",
            started_at=None,
            next_retry_at=None,
            evidence_text=None,
            completed_at=now,
            updated_at=now,
            error_code="WORKER_RESTART_MAX_ATTEMPTS",
        )
    )
    db.commit()
    return int(recoverable.rowcount or 0) + int(exhausted.rowcount or 0)


def claim_next_job(db: Session) -> str | None:
    """Atomically claim the oldest queued job or a retry whose deadline has arrived."""
    now = utc_now()
    eligible = (
        (AIAnalysisJob.status == "queued")
        | (
            (AIAnalysisJob.status == "retry_wait")
            & (AIAnalysisJob.next_retry_at.is_not(None))
            & (AIAnalysisJob.next_retry_at <= now)
        )
    )
    candidate = (
        db.query(AIAnalysisJob.id)
        .filter(eligible)
        .order_by(AIAnalysisJob.created_at.asc())
        .first()
    )
    if candidate is None:
        return None

    job_id = candidate[0]
    result = db.execute(
        update(AIAnalysisJob)
        .where(AIAnalysisJob.id == job_id, eligible)
        .values(
            status="processing",
            started_at=now,
            updated_at=now,
            attempts=AIAnalysisJob.attempts + 1,
            error_code=None,
            next_retry_at=None,
        )
    )
    db.commit()
    return job_id if result.rowcount == 1 else None


def _finish_failed_job(db: Session, job: AIAnalysisJob, error_code: str) -> None:
    job.status = "failed"
    job.error_code = error_code
    job.evidence_text = None
    job.next_retry_at = None
    job.completed_at = utc_now()
    job.updated_at = utc_now()
    db.commit()


def _persist_success(job_id: str, result) -> None:
    db = SessionLocal()
    try:
        job = db.query(AIAnalysisJob).filter(AIAnalysisJob.id == job_id).first()
        if job is None or job.status != "processing":
            return
        job.result_json = result.model_dump(mode="json")
        job.status = "completed"
        job.error_code = None
        job.evidence_text = None
        job.next_retry_at = None
        job.completed_at = utc_now()
        job.updated_at = utc_now()
        db.commit()
    finally:
        db.close()


def _persist_failure(job_id: str, error_code: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(AIAnalysisJob).filter(AIAnalysisJob.id == job_id).first()
        if job is None or job.status != "processing":
            return
        _finish_failed_job(db, job, error_code)
    finally:
        db.close()


def _persist_retry_wait(job_id: str, delay_seconds: int) -> None:
    """Persist a retry deadline without blocking the worker thread."""
    db = SessionLocal()
    try:
        job = db.query(AIAnalysisJob).filter(AIAnalysisJob.id == job_id).first()
        if job is None or job.status != "processing":
            return
        now = utc_now()
        job.status = "retry_wait"
        job.error_code = "AI_PROVIDER_UNAVAILABLE"
        job.started_at = None
        job.next_retry_at = now + timedelta(seconds=delay_seconds)
        job.updated_at = now
        # Keep evidence until the last permitted attempt has been made.
        db.commit()
        logger.warning(
            "Temporary AI provider failure; retry scheduled delay_seconds=%s",
            delay_seconds,
        )
    finally:
        db.close()


def process_job(db: Session, job_id: str) -> None:
    """Compatibility entry point used by unit tests and direct callers."""
    job = db.query(AIAnalysisJob).filter(
        AIAnalysisJob.id == job_id,
        AIAnalysisJob.status == "processing",
    ).first()
    if job is None:
        return
    evidence = job.evidence_text
    analysis_type = job.analysis_type
    if not evidence:
        _finish_failed_job(db, job, "EVIDENCE_UNAVAILABLE")
        return
    try:
        result = analyze_with_gemini(analysis_type, evidence)
    except AIConfigurationError:
        _finish_failed_job(db, job, "AI_NOT_CONFIGURED")
        return
    except AIProviderQuotaExceeded:
        _finish_failed_job(db, job, "AI_QUOTA_EXHAUSTED")
        return
    except AIProviderUnavailable:
        _finish_failed_job(db, job, "AI_PROVIDER_UNAVAILABLE")
        return
    except AIProviderError:
        _finish_failed_job(db, job, "AI_PROVIDER_ERROR")
        return
    job.result_json = result.model_dump(mode="json")
    job.status = "completed"
    job.error_code = None
    job.evidence_text = None
    job.next_retry_at = None
    job.completed_at = utc_now()
    job.updated_at = utc_now()
    db.commit()


def process_claimed_job(job_id: str) -> None:
    """Run one provider attempt without holding a database session during network I/O."""
    db = SessionLocal()
    try:
        job = db.query(AIAnalysisJob).filter(
            AIAnalysisJob.id == job_id,
            AIAnalysisJob.status == "processing",
        ).first()
        if job is None:
            return
        evidence = job.evidence_text
        analysis_type = job.analysis_type
        attempts = job.attempts
        if not evidence:
            _finish_failed_job(db, job, "EVIDENCE_UNAVAILABLE")
            return
    finally:
        db.close()

    try:
        result = analyze_with_gemini(analysis_type, evidence)
        _persist_success(job_id, result)
    except AIConfigurationError:
        _persist_failure(job_id, "AI_NOT_CONFIGURED")
    except AIProviderQuotaExceeded:
        _persist_failure(job_id, "AI_QUOTA_EXHAUSTED")
    except AIProviderUnavailable:
        delay = retry_delay(attempts)
        if delay is None:
            _persist_failure(job_id, "AI_PROVIDER_UNAVAILABLE")
        else:
            _persist_retry_wait(job_id, delay)
    except AIProviderError:
        _persist_failure(job_id, "AI_PROVIDER_ERROR")
    except Exception as exc:
        logger.warning(
            "AI job failed unexpectedly; exception_type=%s",
            type(exc).__name__,
        )
        _persist_failure(job_id, "AI_INTERNAL_ERROR")


def run_worker() -> None:
    """Poll the database and process jobs sequentially."""
    db = SessionLocal()
    try:
        recovered = recover_interrupted_jobs(db)
        if recovered:
            logger.warning("Recovered interrupted AI jobs; count=%s", recovered)
    finally:
        db.close()

    logger.info("CYVANTA AI worker started; polling_interval_seconds=%s", POLL_INTERVAL_SECONDS)
    while True:
        db = SessionLocal()
        try:
            job_id = claim_next_job(db)
        except Exception as exc:
            db.rollback()
            logger.warning("AI worker loop error; exception_type=%s", type(exc).__name__)
            job_id = None
        finally:
            db.close()

        if job_id is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        process_claimed_job(job_id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        run_worker()
    except KeyboardInterrupt:
        logger.info("CYVANTA AI worker stopped by operator.")
