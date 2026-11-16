"""In-memory registry for explicitly approved CYVANTA simulation workers.

This module registers and checks workers only. It does not dispatch jobs,
change execution records, access networks, or execute security operations.
"""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock

from app.action_engine.worker_capabilities import (
    ALLOWED_WORKER_TYPES,
    CAPABILITY_SIMULATION,
    WORKER_TYPE_SIMULATION,
    normalize_capabilities,
)


class WorkerRegistryError(RuntimeError):
    """Base exception for worker registry failures."""


class WorkerNotEligibleError(WorkerRegistryError):
    """Raised when a worker is not eligible for simulation dispatch."""


@dataclass(frozen=True)
class WorkerRecord:
    worker_id: str
    name: str
    worker_type: str
    capabilities: frozenset[str]
    status: str
    created_at: datetime
    updated_at: datetime


class WorkerRegistry:
    """Thread-safe, bounded registry for simulation-only workers."""

    STATUS_REGISTERED = "registered"
    STATUS_ACTIVE = "active"
    STATUS_REVOKED = "revoked"

    def __init__(self, max_workers: int = 1):
        if isinstance(max_workers, bool) or not isinstance(max_workers, int):
            raise ValueError("max_workers must be a positive integer.")
        if max_workers < 1:
            raise ValueError("max_workers must be a positive integer.")

        self._max_workers = max_workers
        self._workers: dict[str, WorkerRecord] = {}
        self._lock = RLock()

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def register(
        self,
        worker_id: str,
        name: str,
        worker_type: str,
        capabilities,
    ) -> WorkerRecord:
        """Register one simulation worker in the registered state."""
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must be a non-empty string.")

        normalized_worker_id = worker_id.strip()

        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string.")

        if (
            not isinstance(worker_type, str)
            or worker_type not in ALLOWED_WORKER_TYPES
        ):
            raise ValueError("Only simulation workers are permitted.")

        normalized = normalize_capabilities(capabilities)

        if CAPABILITY_SIMULATION not in normalized:
            raise ValueError("Simulation capability is required.")

        now = datetime.now(timezone.utc)

        with self._lock:
            if normalized_worker_id in self._workers:
                raise WorkerRegistryError("Worker ID is already registered.")

            if len(self._workers) >= self._max_workers:
                raise WorkerRegistryError("Worker registry capacity reached.")

            record = WorkerRecord(
                worker_id=normalized_worker_id,
                name=name.strip(),
                worker_type=WORKER_TYPE_SIMULATION,
                capabilities=normalized,
                status=self.STATUS_REGISTERED,
                created_at=now,
                updated_at=now,
            )
            self._workers[record.worker_id] = record
            return record

    def get(self, worker_id: str) -> WorkerRecord | None:
        """Return a worker record, or None when it does not exist."""
        if not isinstance(worker_id, str) or not worker_id.strip():
            return None
        worker_id = worker_id.strip()
        with self._lock:
            return self._workers.get(worker_id)

    def list_workers(self) -> tuple[WorkerRecord, ...]:
        """Return an immutable snapshot of registered workers."""
        with self._lock:
            return tuple(self._workers.values())

    def activate(self, worker_id: str) -> WorkerRecord:
        """Explicitly activate a registered simulation worker."""
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise WorkerRegistryError("Worker is not registered.")
        worker_id = worker_id.strip()
        with self._lock:
            record = self._workers.get(worker_id)
            if record is None:
                raise WorkerRegistryError("Worker is not registered.")

            if record.status != self.STATUS_REGISTERED:
                raise WorkerRegistryError(
                    "Only registered workers can be activated."
                )

            updated = replace(
                record,
                status=self.STATUS_ACTIVE,
                updated_at=datetime.now(timezone.utc),
            )
            self._workers[worker_id] = updated
            return updated

    def revoke(self, worker_id: str) -> WorkerRecord:
        """Revoke a registered or active worker permanently."""
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise WorkerRegistryError("Worker is not registered.")
        worker_id = worker_id.strip()
        with self._lock:
            record = self._workers.get(worker_id)
            if record is None:
                raise WorkerRegistryError("Worker is not registered.")

            if record.status == self.STATUS_REVOKED:
                raise WorkerRegistryError("Worker is already revoked.")

            updated = replace(
                record,
                status=self.STATUS_REVOKED,
                updated_at=datetime.now(timezone.utc),
            )
            self._workers[worker_id] = updated
            return updated

    @contextmanager
    def eligible_worker(self, worker_id: str):
        """Hold the registry lock while an eligible worker is in use."""
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise WorkerNotEligibleError("Worker is not registered.")

        normalized_id = worker_id.strip()

        with self._lock:
            record = self._workers.get(normalized_id)

            if record is None:
                raise WorkerNotEligibleError("Worker is not registered.")

            if record.status != self.STATUS_ACTIVE:
                raise WorkerNotEligibleError("Worker is not active.")

            if record.worker_type != WORKER_TYPE_SIMULATION:
                raise WorkerNotEligibleError("Worker type is not eligible.")

            if CAPABILITY_SIMULATION not in record.capabilities:
                raise WorkerNotEligibleError(
                    "Worker lacks the required simulation capability."
                )

            # The RLock remains held until the caller exits this context.
            yield record

    def require_eligible(self, worker_id: str) -> WorkerRecord:
        """Require an active simulation worker with simulation capability.

        This is an eligibility check only. It never starts an execution.
        """
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise WorkerNotEligibleError("Worker is not registered.")
        worker_id = worker_id.strip()
        with self._lock:
            record = self._workers.get(worker_id)

            if record is None:
                raise WorkerNotEligibleError("Worker is not registered.")

            if record.status != self.STATUS_ACTIVE:
                raise WorkerNotEligibleError("Worker is not active.")

            if record.worker_type != WORKER_TYPE_SIMULATION:
                raise WorkerNotEligibleError("Worker type is not permitted.")

            if CAPABILITY_SIMULATION not in record.capabilities:
                raise WorkerNotEligibleError(
                    "Worker does not have simulation capability."
                )

            return record



