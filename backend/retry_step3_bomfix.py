from pathlib import Path
from datetime import datetime, timedelta
import ast, shutil, subprocess, sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'app' / 'ai' / 'worker.py'
source = TARGET.read_text(encoding='utf-8-sig')

def span(code, name):
    tree = ast.parse(code, filename=str(TARGET))
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(found) != 1:
        raise RuntimeError(f'{name}: expected one top-level function, found {len(found)}')
    return found[0].lineno - 1, found[0].end_lineno

def replace_func(code, name, body):
    a, b = span(code, name)
    lines = code.splitlines(keepends=True)
    return ''.join(lines[:a]) + body.rstrip() + '\\n\\n' + ''.join(lines[b:])

if 'from datetime import timedelta' not in source:
    source = source.replace('import time\\n', 'import time\\nfrom datetime import timedelta\\n', 1)
if '    AIProviderQuotaExceeded,' not in source:
    source = source.replace('    AIProviderError,\\n', '    AIProviderError,\\n    AIProviderQuotaExceeded,\\n', 1)

source = replace_func(source, 'recover_interrupted_jobs', '''def recover_interrupted_jobs(db: Session) -> int:
    now = utc_now()
    recoverable = db.execute(
        update(AIAnalysisJob)
        .where(AIAnalysisJob.status == 'processing', AIAnalysisJob.attempts < MAX_ATTEMPTS)
        .values(status='queued', started_at=None, next_retry_at=None,
                updated_at=now, error_code='WORKER_RESTART_RECOVERY')
    )
    exhausted = db.execute(
        update(AIAnalysisJob)
        .where(AIAnalysisJob.status == 'processing', AIAnalysisJob.attempts >= MAX_ATTEMPTS)
        .values(status='failed', started_at=None, next_retry_at=None, evidence_text=None,
                completed_at=now, updated_at=now, error_code='WORKER_RESTART_MAX_ATTEMPTS')
    )
    db.commit()
    return int(recoverable.rowcount or 0) + int(exhausted.rowcount or 0)
''')

source = replace_func(source, 'claim_next_job', '''def claim_next_job(db: Session) -> str | None:
    now = utc_now()
    eligible = (
        (AIAnalysisJob.status == 'queued')
        | ((AIAnalysisJob.status == 'retry_wait')
           & (AIAnalysisJob.next_retry_at.is_not(None))
           & (AIAnalysisJob.next_retry_at <= now))
    )
    candidate = (db.query(AIAnalysisJob.id).filter(eligible)
                 .order_by(AIAnalysisJob.created_at.asc()).first())
    if candidate is None:
        return None
    job_id = candidate[0]
    result = db.execute(
        update(AIAnalysisJob).where(AIAnalysisJob.id == job_id, eligible).values(
            status='processing', started_at=now, updated_at=now,
            attempts=AIAnalysisJob.attempts + 1, error_code=None, next_retry_at=None
        )
    )
    db.commit()
    return job_id if result.rowcount == 1 else None
''')

source = replace_func(source, '_finish_failed_job', '''def _finish_failed_job(db: Session, job: AIAnalysisJob, error_code: str) -> None:
    job.status = 'failed'
    job.error_code = error_code
    job.evidence_text = None
    job.next_retry_at = None
    job.completed_at = utc_now()
    job.updated_at = utc_now()
    db.commit()
''')

source = replace_func(source, '_persist_success', '''def _persist_success(job_id: str, result) -> None:
    db = SessionLocal()
    try:
        job = db.query(AIAnalysisJob).filter(AIAnalysisJob.id == job_id).first()
        if job is None or job.status != 'processing':
            return
        job.result_json = result.model_dump(mode='json')
        job.status = 'completed'
        job.error_code = None
        job.evidence_text = None
        job.next_retry_at = None
        job.completed_at = utc_now()
        job.updated_at = utc_now()
        db.commit()
    finally:
        db.close()
''')

source = replace_func(source, 'process_job', '''def process_job(db: Session, job_id: str) -> None:
    job = db.query(AIAnalysisJob).filter(
        AIAnalysisJob.id == job_id, AIAnalysisJob.status == 'processing'
    ).first()
    if job is None:
        return
    evidence = job.evidence_text
    analysis_type = job.analysis_type
    if not evidence:
        _finish_failed_job(db, job, 'EVIDENCE_UNAVAILABLE')
        return
    try:
        result = analyze_with_gemini(analysis_type, evidence)
    except AIConfigurationError:
        _finish_failed_job(db, job, 'AI_NOT_CONFIGURED')
        return
    except AIProviderQuotaExceeded:
        _finish_failed_job(db, job, 'AI_QUOTA_EXHAUSTED')
        return
    except AIProviderUnavailable:
        _finish_failed_job(db, job, 'AI_PROVIDER_UNAVAILABLE')
        return
    except AIProviderError:
        _finish_failed_job(db, job, 'AI_PROVIDER_ERROR')
        return
    job.result_json = result.model_dump(mode='json')
    job.status = 'completed'
    job.error_code = None
    job.evidence_text = None
    job.next_retry_at = None
    job.completed_at = utc_now()
    job.updated_at = utc_now()
    db.commit()
''')

source = replace_func(source, 'process_claimed_job', '''def process_claimed_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(AIAnalysisJob).filter(
            AIAnalysisJob.id == job_id, AIAnalysisJob.status == 'processing'
        ).first()
        if job is None:
            return
        evidence = job.evidence_text
        analysis_type = job.analysis_type
        attempts = job.attempts
        if not evidence:
            _finish_failed_job(db, job, 'EVIDENCE_UNAVAILABLE')
            return
    finally:
        db.close()

    try:
        result = analyze_with_gemini(analysis_type, evidence)
        _persist_success(job_id, result)
    except AIConfigurationError:
        _persist_failure(job_id, 'AI_NOT_CONFIGURED')
    except AIProviderQuotaExceeded:
        _persist_failure(job_id, 'AI_QUOTA_EXHAUSTED')
    except AIProviderUnavailable:
        delay = retry_delay(attempts)
        if delay is None:
            _persist_failure(job_id, 'AI_PROVIDER_UNAVAILABLE')
        else:
            _persist_retry_wait(job_id, delay)
    except AIProviderError:
        _persist_failure(job_id, 'AI_PROVIDER_ERROR')
    except Exception as exc:
        logger.warning('AI job failed unexpectedly; exception_type=%s', type(exc).__name__)
        _persist_failure(job_id, 'AI_INTERNAL_ERROR')
''')

helper = '''def _persist_retry_wait(job_id: str, delay_seconds: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(AIAnalysisJob).filter(AIAnalysisJob.id == job_id).first()
        if job is None or job.status != 'processing':
            return
        now = utc_now()
        job.status = 'retry_wait'
        job.error_code = 'AI_PROVIDER_UNAVAILABLE'
        job.started_at = None
        job.next_retry_at = now + timedelta(seconds=delay_seconds)
        job.updated_at = now
        db.commit()
        logger.warning('Temporary AI provider failure; retry scheduled delay_seconds=%s', delay_seconds)
    finally:
        db.close()
'''
insert_at, _ = span(source, 'process_job')
lines = source.splitlines(keepends=True)
lines.insert(insert_at, helper + '\\n')
source = ''.join(lines)
ast.parse(source, filename=str(TARGET))

backup = ROOT / 'backups' / f'durable_retry_step3_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(TARGET, backup / 'worker.py')
try:
    TARGET.write_text(source, encoding='utf-8-sig')
    compile_result = subprocess.run([sys.executable, '-m', 'compileall', '-q', 'app'],
                                    cwd=ROOT, capture_output=True, text=True)
    if compile_result.returncode:
        raise RuntimeError(compile_result.stdout + compile_result.stderr)
    tests = subprocess.run([sys.executable, '-m', 'pytest', 'tests', '-q'],
                           cwd=ROOT, capture_output=True, text=True)
    print(tests.stdout)
    if tests.stderr:
        print(tests.stderr, file=sys.stderr)
    if tests.returncode:
        raise RuntimeError('Full test suite failed')
except Exception as exc:
    shutil.copy2(backup / 'worker.py', TARGET)
    raise SystemExit(f'Patch failed; worker.py restored from {backup}\\n{exc}')

print('STEP 3 SUCCESSFUL')
print(f'Backup: {backup}')
print('Updated: app/ai/worker.py')
print('Durable retry_wait scheduling enabled; no provider retry sleep.')
