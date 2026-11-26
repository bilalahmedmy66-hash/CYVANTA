from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path.cwd()
if ROOT.name.lower() != "backend":
    raise SystemExit("Run this script from CYVANTA\\backend.")
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    raise SystemExit("Backend virtual-environment Python was not found.")

SCHEMAS = ROOT / "app" / "ai" / "schemas.py"
SERVICE = ROOT / "app" / "ai" / "service.py"
for path in (SCHEMAS, SERVICE):
    if not path.is_file():
        raise SystemExit(f"Required file not found: {path}")

schemas = SCHEMAS.read_text(encoding="utf-8").replace("\r\n", "\n")
service = SERVICE.read_text(encoding="utf-8").replace("\r\n", "\n")

status_anchor = '    status: Literal["queued", "processing", "completed", "failed"]\n'
attempts_anchor = "    attempts: int\n"
updated_anchor = "    updated_at: datetime\n"
quota_class_anchor = (
    'class AIProviderUnavailable(AIProviderError):\n'
    '    """The upstream model service is temporarily unavailable."""\n'
)
temporary_anchor = "def _is_temporary_provider_failure(exc: Exception) -> bool:\n"
classification_anchor = "        if _is_temporary_provider_failure(exc):\n"

checks = [
    (schemas.count(status_anchor) == 1, "AIJobResponse status anchor"),
    (schemas.count(attempts_anchor) == 1, "AIJobResponse attempts anchor"),
    (schemas.count(updated_anchor) == 1, "AIJobResponse updated_at anchor"),
    (schemas.count('"retry_wait"') == 0, "retry_wait not already present"),
    (service.count(quota_class_anchor) == 1, "AIProviderUnavailable class anchor"),
    (service.count(temporary_anchor) == 1, "temporary classifier anchor"),
    (service.count(classification_anchor) == 1, "provider classification anchor"),
    ("AIProviderQuotaExceeded" not in service, "quota exception not already present"),
]
for passed, label in checks:
    if not passed:
        raise SystemExit(f"Preflight failed: {label}.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / "backups" / f"retry_step2_{stamp}"
(backup / "app" / "ai").mkdir(parents=True, exist_ok=True)
shutil.copy2(SCHEMAS, backup / "app" / "ai" / "schemas.py")
shutil.copy2(SERVICE, backup / "app" / "ai" / "service.py")

new_schemas = schemas.replace(
    status_anchor,
    '    status: Literal["queued", "processing", "retry_wait", "completed", "failed"]\n',
    1,
).replace(
    attempts_anchor,
    "    attempts: int\n    next_retry_at: datetime | None = None\n",
    1,
)

new_service = service.replace(
    quota_class_anchor,
    quota_class_anchor
    + '\n\nclass AIProviderQuotaExceeded(AIProviderError):\n'
    + '    """The provider quota or rate limit is exhausted; do not auto-retry."""\n',
    1,
)
quota_helper = (
    "def _is_quota_exhaustion(exc: Exception) -> bool:\n"
    '    """Detect quota/rate-limit exhaustion before temporary-outage classification."""\n'
    "    candidates = [\n"
    '        getattr(exc, "code", None),\n'
    '        getattr(exc, "status_code", None),\n'
    '        getattr(getattr(exc, "response", None), "status_code", None),\n'
    "        str(exc),\n"
    "    ]\n"
    '    normalized = " ".join(str(value) for value in candidates if value is not None).lower()\n'
    "    return any(marker in normalized for marker in (\n"
    '        "429", "resource_exhausted", "quota_exceeded", "quota exceeded",\n'
    '        "rate_limit", "rate limit",\n'
    "    ))\n\n\n"
)
new_service = new_service.replace(temporary_anchor, quota_helper + temporary_anchor, 1)
new_service = new_service.replace(
    classification_anchor,
    "        if _is_quota_exhaustion(exc):\n"
    "            raise AIProviderQuotaExceeded(\n"
    '                "Gemini quota is exhausted. Check provider quota before retrying."\n'
    "            ) from exc\n"
    + classification_anchor,
    1,
)

try:
    SCHEMAS.write_text(new_schemas, encoding="utf-8", newline="\n")
    SERVICE.write_text(new_service, encoding="utf-8", newline="\n")

    result = subprocess.run(
        [str(PYTHON), "-m", "compileall", "-q", "app"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Python compilation failed.")

    # Pure local checks: no Gemini/network call and no credentials involved.
    check_code = (
        "from app.ai.schemas import AIJobResponse\n"
        "from app.ai.service import _is_quota_exhaustion, _is_temporary_provider_failure\n"
        "assert _is_quota_exhaustion(Exception('HTTP 429 resource_exhausted'))\n"
        "assert _is_quota_exhaustion(Exception('quota exceeded'))\n"
        "assert not _is_quota_exhaustion(Exception('HTTP 504 Gateway Timeout'))\n"
        "assert _is_temporary_provider_failure(Exception('HTTP 504 Gateway Timeout'))\n"
        "assert 'retry_wait' in AIJobResponse.model_fields['status'].annotation.__args__\n"
        "assert 'next_retry_at' in AIJobResponse.model_fields\n"
        "print('Schema and provider-classification smoke tests passed.')\n"
    )
    result = subprocess.run(
        [str(PYTHON), "-c", check_code],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Schema/provider smoke test failed.")

    result = subprocess.run(
        [str(PYTHON), "-m", "pytest", "tests", "-q"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Existing test suite failed.")

except Exception as exc:
    print(f"STEP 2 FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    shutil.copy2(backup / "app" / "ai" / "schemas.py", SCHEMAS)
    shutil.copy2(backup / "app" / "ai" / "service.py", SERVICE)
    print(f"Rollback complete. Backup: {backup}", file=sys.stderr)
    raise SystemExit(1)

print("\nSTEP 2 SUCCESSFUL")
print(f"Backup: {backup}")
print("Updated: app/ai/schemas.py")
print("Updated: app/ai/service.py")
print("Added retry_wait response status and next_retry_at.")
print("Added terminal quota-exhaustion classification.")
