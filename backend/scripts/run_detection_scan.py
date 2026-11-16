"""Run one manual CYVANTA deterministic detection scan."""

import sys
from pathlib import Path

# Make the backend directory available for application imports.
BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.security.detection_orchestrator import (
    DetectionMigrationsUnavailable,
    run_detection_scan,
)

def main() -> int:
    print("=" * 55)
    print("CYVANTA - MANUAL DETECTION SCAN")
    print("=" * 55)

    try:
        result = run_detection_scan()

    except DetectionMigrationsUnavailable as exc:
        print("\nERROR: Required database migrations are unavailable.")
        print(f"Details: {exc}")
        return 2

    except Exception:
        print("\nERROR: Detection scan failed.")
        print("Sensitive internal details have been withheld.")
        return 1

    print("\nSCAN COMPLETED")
    print("-" * 55)
    print(f"Findings detected : {result['detected']}")
    print(f"Findings created  : {result['created']}")
    print(f"Findings updated  : {result['updated']}")
    print(f"Findings reopened : {result['reopened']}")
    print(f"Findings unchanged: {result['unchanged']}")
    print(f"Findings processed: {result['processed']}")
    print("-" * 55)

    print("\nExecution mode: ALERT-ONLY")
    print("Containment actions: NOT EXECUTED")
    print("External systems contacted: NONE")

    return 0


if __name__ == "__main__":
    sys.exit(main())
