from pathlib import Path
from datetime import datetime
import ast
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent
target = root / "app" / "ai" / "worker.py"
source = target.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(target))

def function_span(tree, name):
    matches = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one top-level function {name}; found {len(matches)}")
    node = matches[0]
    return node.lineno - 1, node.end_lineno, node

def replace_function(current, name, replacement):
    parsed = ast.parse(current)
    start, end, _ = function_span(parsed, name)
    lines = current.splitlines(keepends=True)
    return "".join(lines[:start]) + replacement.rstrip() + "\n\n" + "".join(lines[end:])

# Import timedelta and the quota exception without broad replacements.
if "from datetime import timedelta" not in source:
    source = source.replace("import time\n", "import time\nfrom datetime import timedelta\n", 1)
if "    AIProviderQuotaExceeded," not in source:
    source = source.replace(
        "    AIProviderError,\n",
        "    AIProviderError,\n    AIProviderQuotaExceeded,\n",
        1,
    )

recover = '''def recover_interrupted_jobs(db: Session) -> int:
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
'''

claim = '''def claim_next_job(db: Session) -> str | None:
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
'''

finish_failed = '''def _finish_failed_job(db: Session, job: AIAnalysisJob, error_code: str) -> None:
    job.status = "failed"
    job.error_code = error_code
    job.evidence_text = None
    job.next_retry_at = None
    job.completed_at = utc_now()
    job.updated_at = utc_now()
    db.commit()
'''

persist_success = '''def _persist_success(job_id: str, result) -> None:
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
'''

retry_helper = '''def _persist_retry_wait(job_id: str, delay_seconds: int) -> None:
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
        # Preserve evidence only while a retry remains possible.
        db.commit()
        logger.warning(
            "Temporary AI provider failure; retry scheduled delay_seconds=%s",
            delay_seconds,
        )
    finally:
        db.close()
'''

process_job = '''def process_job(db: Session, job_id: str) -> None:
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
'''

process_claimed = '''def process_claimed_job(job_id: str) -> None:
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
'''

# Replace each top-level function by AST line range, from bottom to top.
for name, body in [
    ("recover_interrupted_jobs", recover),
    ("claim_next_job", claim),
    ("_finish_failed_job", finish_failed),
    ("_persist_success", persist_success),
    ("process_job", process_job),
    ("process_claimed_job", process_claimed),
]:
    source = replace_function(source, name, body)

# Insert helper immediately before process_job.
parsed = ast.parse(source)
start_line, _, _ = function_span(parsed, "process_job")
lines = source.splitlines(keepends=True)
lines.insert(start_line, retry_helper + "\n")
source = "".join(lines)

ast.parse(source, filename=str(target))

backup = root / "backups" / f"durable_retry_step3_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(target, backup / "worker.py")

try:
    target.write_text(source, encoding="utf-8")
    compile_run = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "app"],
        cwd=root, text=True, capture_output=True,
    )
    if compile_run.returncode:
        raise RuntimeError("compileall failed:\n" + compile_run.stdout + compile_run.stderr)

    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=root, text=True, capture_output=True,
    )
    print(tests.stdout)
    if tests.stderr:
        print(tests.stderr, file=sys.stderr)
    if tests.returncode:
        raise RuntimeError("Full test suite failed")
except Exception as exc:
    shutil.copy2(backup / "worker.py", target)
    raise SystemExit(f"STEP 3 FAILED; worker.py restored from {backup}\n{exc}")

print("STEP 3 SUCCESSFUL")
print(f"Backup: {backup}")
print("Updated: app/ai/worker.py")
print("Durable retry_wait scheduling enabled; no provider retry sleep.")
