from pathlib import Path
from datetime import datetime, timedelta
import ast, shutil, subprocess, sys

root = Path(__file__).resolve().parent
target = root / "app" / "ai" / "worker.py"
original = target.read_text(encoding="utf-8")
text = original

def rep(old, new, label):
    global text
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one exact match, found {n}; no project changes made")
    text = text.replace(old, new, 1)

rep('''    AIProviderError,
    AIProviderUnavailable,
    analyze_with_gemini,
''', '''    AIProviderError,
    AIProviderQuotaExceeded,
    AIProviderUnavailable,
    analyze_with_gemini,
''', "provider imports")

rep('''def recover_interrupted_jobs(db: Session) -> int:
    \\"\\"\\"Requeue jobs left processing by a previously stopped worker.\\"\\"\\"
    result = db.execute(
        update(AIAnalysisJob)
        .where(AIAnalysisJob.status == "processing")
        .values(
            status="queued",
            started_at=None,
            updated_at=utc_now(),
            error_code="WORKER_RESTART_RECOVERY",
        )
    )
    db.commit()
    return int(result.rowcount or 0)
''', '''def recover_interrupted_jobs(db: Session) -> int:
    \\"\\"\\"Recover interrupted jobs without exceeding the attempt limit.\\"\\"\\"
    now = utc_now()
    recoverable = db.execute(
        update(AIAnalysisJob)
        .where(AIAnalysisJob.status == "processing", AIAnalysisJob.attempts < MAX_ATTEMPTS)
        .values(status="queued", started_at=None, next_retry_at=None,
                updated_at=now, error_code="WORKER_RESTART_RECOVERY")
    )
    exhausted = db.execute(
        update(AIAnalysisJob)
        .where(AIAnalysisJob.status == "processing", AIAnalysisJob.attempts >= MAX_ATTEMPTS)
        .values(status="failed", started_at=None, next_retry_at=None, evidence_text=None,
                completed_at=now, updated_at=now, error_code="WORKER_RESTART_MAX_ATTEMPTS")
    )
    db.commit()
    return int(recoverable.rowcount or 0) + int(exhausted.rowcount or 0)
''', "interrupted-job recovery")

rep('''def claim_next_job(db: Session) -> str | None:
    \\"\\"\\"Atomically claim the oldest queued job.\\"\\"\\"
    candidate = (
        db.query(AIAnalysisJob.id)
        .filter(AIAnalysisJob.status == "queued")
        .order_by(AIAnalysisJob.created_at.asc())
        .first()
    )
    if candidate is None:
        return None

    job_id = candidate[0]
    result = db.execute(
        update(AIAnalysisJob)
        .where(AIAnalysisJob.id == job_id, AIAnalysisJob.status == "queued")
        .values(
            status="processing",
            started_at=utc_now(),
            updated_at=utc_now(),
            attempts=AIAnalysisJob.attempts + 1,
            error_code=None,
        )
    )
    db.commit()
    return job_id if result.rowcount == 1 else None
''', '''def claim_next_job(db: Session) -> str | None:
    \\"\\"\\"Claim the oldest queued job or a retry whose deadline has arrived.\\"\\"\\"
    now = utc_now()
    eligible = (
        (AIAnalysisJob.status == "queued")
        | ((AIAnalysisJob.status == "retry_wait")
           & (AIAnalysisJob.next_retry_at.is_not(None))
           & (AIAnalysisJob.next_retry_at <= now))
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
        .values(status="processing", started_at=now, updated_at=now,
                attempts=AIAnalysisJob.attempts + 1, error_code=None, next_retry_at=None)
    )
    db.commit()
    return job_id if result.rowcount == 1 else None
''', "job claiming")

rep('''        job.evidence_text = None
        job.completed_at = utc_now()
''', '''        job.evidence_text = None
        job.next_retry_at = None
        job.completed_at = utc_now()
''', "success timestamp cleanup")
rep('''    job.evidence_text = None
    job.completed_at = utc_now()
''', '''    job.evidence_text = None
    job.next_retry_at = None
    job.completed_at = utc_now()
''', "failure timestamp cleanup")

rep('''def process_job(db: Session, job_id: str) -> None:
''', '''def _persist_retry_wait(job_id: str, delay_seconds: int) -> None:
    \\"\\"\\"Save a retry deadline without blocking the worker.\\"\\"\\"
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
        # Retain evidence only while a retry remains possible.
        db.commit()
        logger.warning("Temporary AI provider failure; retry scheduled delay_seconds=%s", delay_seconds)
    finally:
        db.close()


def process_job(db: Session, job_id: str) -> None:
''', "retry persistence helper")

rep('''    except AIProviderUnavailable:
        _finish_failed_job(db, job, "AI_PROVIDER_UNAVAILABLE")
        return
    except AIProviderError:
''', '''    except AIProviderQuotaExceeded:
        _finish_failed_job(db, job, "AI_QUOTA_EXHAUSTED")
        return
    except AIProviderUnavailable:
        _finish_failed_job(db, job, "AI_PROVIDER_UNAVAILABLE")
        return
    except AIProviderError:
''', "compatibility quota handling")

start = text.find("def process_claimed_job(job_id: str) -> None:\n")
end = text.find("\ndef run_worker() -> None:\n", start)
if start < 0 or end < 0:
    raise RuntimeError("Could not find process_claimed_job boundaries; no project changes made")

replacement = '''def process_claimed_job(job_id: str) -> None:
    \\"\\"\\"Run one provider attempt without holding a database session during network I/O.\\"\\"\\"
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
        logger.warning("AI job failed unexpectedly; exception_type=%s", type(exc).__name__)
        _persist_failure(job_id, "AI_INTERNAL_ERROR")

'''
text = text[:start] + replacement + text[end:]
ast.parse(text, filename=str(target))

backup = root / "backups" / f"durable_retry_step3_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(target, backup / "worker.py")

try:
    target.write_text(text, encoding="utf-8")
    compile_run = subprocess.run([sys.executable, "-m", "compileall", "-q", "app"],
                                 cwd=root, text=True, capture_output=True)
    if compile_run.returncode:
        raise RuntimeError(compile_run.stdout + compile_run.stderr)
    tests = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"],
                           cwd=root, text=True, capture_output=True)
    print(tests.stdout)
    if tests.stderr:
        print(tests.stderr, file=sys.stderr)
    if tests.returncode:
        raise RuntimeError("Full test suite failed")
except Exception as exc:
    shutil.copy2(backup / "worker.py", target)
    raise SystemExit(f"STEP 3 FAILED; original worker.py restored from {backup}\n{exc}")

print("STEP 3 SUCCESSFUL")
print(f"Backup: {backup}")
print("Updated: app/ai/worker.py")
print("Durable retry_wait scheduling is enabled; no provider retry sleep.")
