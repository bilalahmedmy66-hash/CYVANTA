
from pathlib import Path
from datetime import datetime
import shutil

path = Path("frontend/src/WorkspacePage.jsx")

if not path.exists():
    raise SystemExit("ERROR: WorkspacePage.jsx not found.")

raw = path.read_bytes()
text = raw.decode("utf-8-sig")

backup = path.with_name(
    f"WorkspacePage.jsx.backup_encoding_{datetime.now():%Y%m%d_%H%M%S}"
)
shutil.copy2(path, backup)

replacements = {
    "â€”": "—",
    "Ã¢â‚¬Â¦": "…",
}

for old, new in replacements.items():
    if old not in text:
        raise SystemExit(
            f"ERROR: Expected corrupted text not found: {old!r}. "
            "Original file remains unchanged."
        )
    text = text.replace(old, new)

if "\ufeff" in text:
    raise SystemExit("ERROR: Unexpected BOM remains.")

path.write_text(text, encoding="utf-8", newline="\n")

verified = path.read_text(encoding="utf-8")

if "â€”" in verified or "Ã¢â‚¬Â¦" in verified:
    shutil.copy2(backup, path)
    raise SystemExit("ERROR: Verification failed. Original restored.")

print("ENCODING FIX SUCCESSFUL")
print(f"Backup: {backup}")
print("UTF-8 encoding verified.")
