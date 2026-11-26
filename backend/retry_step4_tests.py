from pathlib import Path
from datetime import timedelta
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "tests" / "test_ai_worker.py"
if not TARGET.is_file():
    raise SystemExit(f"Test file not found: {TARGET}")

original = TARGET.read_text(encoding="utf-8-sig")
marker = "# CYVANTA DURABLE RETRY TESTS"
if marker in original:
    raise SystemExit("Durable retry tests already appear to be present; refusing to append duplicates.")

addition = r