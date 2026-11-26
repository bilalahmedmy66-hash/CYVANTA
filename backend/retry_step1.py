from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path.cwd()
if ROOT.name.lower() != "backend":
    raise SystemExit("Run this script from the CYVANTA\\backend directory.")

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    raise SystemExit(f"Virtual-environment Python not found: {PYTHON}")

MODEL = ROOT / "app" / "models.py"
MAIN = ROOT / "app" / "main.py"
MIGRATION = ROOT / "app" / "database" / "migrations.py"

for path in (MODEL, MAIN):
    if not path.is_file():
        raise SystemExit(f"Required file not found: {path}")

model_text = MODEL.read_text(encoding="utf-8").replace("\r\n", "\n")
main_text = MAIN.read_text(encoding="utf-8").replace("\r\n", "\n")

model_anchor = (
    '    updated_at: Mapped[datetime] = mapped_column('
    'DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)'
)
main_import_anchor = "from app.database.session import engine\n"
main_lifespan_anchor = (
    "    Base.metadata.create_all(bind=engine)\n"
    "    yield\n"
)

if "next_retry_at:" in model_text:
    raise SystemExit("Preflight stopped: next_retry_at already exists in models.py.")
if model_text.count(model_anchor) != 1:
    raise SystemExit("Preflight stopped: expected AIAnalysisJob updated_at anchor was not unique.")
if "ensure_ai_analysis_job_retry_column" in main_text:
    raise SystemExit("Preflight stopped: migration hook already exists in main.py.")
if main_text.count(main_import_anchor) != 1:
    raise SystemExit("Preflight stopped: expected engine import was not unique.")
if main_text.count(main_lifespan_anchor) != 1:
    raise SystemExit("Preflight stopped: expected lifespan block was not unique.")
if MIGRATION.exists():
    raise SystemExit("Preflight stopped: app/database/migrations.py already exists.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = ROOT / "backups" / f"retry_step1_{stamp}"
(backup_dir / "app").mkdir(parents=True, exist_ok=True)
shutil.copy2(MODEL, backup_dir / "app" / "models.py")
shutil.copy2(MAIN, backup_dir / "app" / "main.py")

new_model_text = model_text.replace(
    model_anchor,
    model_anchor
    + "\n"
    + "    next_retry_at: Mapped[datetime | None] = mapped_column("
    + "DateTime(timezone=True), nullable=True, index=True)",
    1,
)

new_main_text = main_text.replace(
    main_import_anchor,
    main_import_anchor
    + "from app.database.migrations import ensure_ai_analysis_job_retry_column\n",
    1,
).replace(
    main_lifespan_anchor,
    "    Base.metadata.create_all(bind=engine)\n"
    "    ensure_ai_analysis_job_retry_column(engine)\n"
    "    yield\n",
    1,
)

migration_text = '''# Idempotent SQLite compatibility migrations for CYVANTA.

from sqlalchemy import inspect, text


def ensure_ai_analysis_job_retry_column(engine) -> None:
    # Add next_retry_at to an existing SQLite AI job table, if needed.
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "ai_analysis_jobs" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("ai_analysis_jobs")}
    if "next_retry_at" in columns:
        return

    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE ai_analysis_jobs ADD COLUMN next_retry_at DATETIME")
        )
'''

try:
    MODEL.write_text(new_model_text, encoding="utf-8", newline="\n")
    MAIN.write_text(new_main_text, encoding="utf-8", newline="\n")
    MIGRATION.write_text(migration_text, encoding="utf-8", newline="\n")

    compile_result = subprocess.run(
        [str(PYTHON), "-m", "compileall", "-q", "app"],
        cwd=ROOT,
        check=False,
    )
    if compile_result.returncode:
        raise RuntimeError("Python compilation failed.")

    smoke_code = (
        "from sqlalchemy import create_engine, inspect, text\n"
        "from app.database.migrations import ensure_ai_analysis_job_retry_column\n"
        "engine = create_engine('sqlite:///:memory:')\n"
        "with engine.begin() as connection:\n"
        "    connection.execute(text('CREATE TABLE ai_analysis_jobs (id VARCHAR(36) PRIMARY KEY, status VARCHAR(20))'))\n"
        "ensure_ai_analysis_job_retry_column(engine)\n"
        "ensure_ai_analysis_job_retry_column(engine)\n"
        "columns = {column['name'] for column in inspect(engine).get_columns('ai_analysis_jobs')}\n"
        "assert 'next_retry_at' in columns, columns\n"
        "print('Migration smoke test passed; repeated invocation is safe.')\n"
        "engine.dispose()\n"
    )
    smoke_result = subprocess.run(
        [str(PYTHON), "-c", smoke_code],
        cwd=ROOT,
        check=False,
    )
    if smoke_result.returncode:
        raise RuntimeError("Migration smoke test failed.")

    test_result = subprocess.run(
        [str(PYTHON), "-m", "pytest", "tests", "-q"],
        cwd=ROOT,
        check=False,
    )
    if test_result.returncode:
        raise RuntimeError("Existing test suite failed.")

except Exception as exc:
    print(f"STEP 1 FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    print("Restoring backed-up files...", file=sys.stderr)
    shutil.copy2(backup_dir / "app" / "models.py", MODEL)
    shutil.copy2(backup_dir / "app" / "main.py", MAIN)
    if MIGRATION.exists():
        MIGRATION.unlink()
    print(f"Rollback complete. Backup: {backup_dir}", file=sys.stderr)
    raise SystemExit(1)

print("\nSTEP 1 SUCCESSFUL")
print(f"Backup: {backup_dir}")
print("Updated: app/models.py")
print("Updated: app/main.py")
print("Created: app/database/migrations.py")
print("Added: AIAnalysisJob.next_retry_at")
