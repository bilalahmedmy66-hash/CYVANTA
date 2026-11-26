"""Deterministic lifecycle state management for CYVANTA FORTRESS V2.

This module manages logical agent states only. It does not launch
processes, schedule jobs, grant permissions, or execute actions.
"""

from dataclasses import dataclass
from enum import Enum
from threading import RLock
from types import MappingProxyType
from typing import Mapping

from app.agents.identity import AGENTS


LIFECYCLE_VERSION = "2.0.0"


class LifecycleStatus(str, Enum):
    REGISTERED = "registered"
    INACTIVE = "inactive"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class LifecycleError(ValueError):
    """Raised when a lifecycle operation is invalid."""


class UnknownAgentError(LifecycleError):
    """Raised when an agent identity is not registered."""


class InvalidTransitionError(LifecycleError):
    """Raised when a requested state transition is prohibited."""


class RevisionConflictError(LifecycleError):
    """Raised when a caller supplies a stale revision number."""


@dataclass(frozen=True, slots=True)
class LifecycleRecord:
    agent_id: str
    status: LifecycleStatus
    revision: int
    version: str


_ALLOWED_TRANSITIONS: Mapping[
    LifecycleStatus, frozenset[LifecycleStatus]
] = MappingProxyType(
    {
        LifecycleStatus.REGISTERED: frozenset(
            {
                LifecycleStatus.INACTIVE,
                LifecycleStatus.SCHEDULED,
                LifecycleStatus.SUSPENDED,
                LifecycleStatus.RETIRED,
            }
        ),
        LifecycleStatus.INACTIVE: frozenset(
            {
                LifecycleStatus.SCHEDULED,
                LifecycleStatus.SUSPENDED,
                LifecycleStatus.RETIRED,
            }
        ),
        LifecycleStatus.SCHEDULED: frozenset(
            {
                LifecycleStatus.RUNNING,
                LifecycleStatus.INACTIVE,
                LifecycleStatus.FAILED,
                LifecycleStatus.SUSPENDED,
            }
        ),
        LifecycleStatus.RUNNING: frozenset(
            {
                LifecycleStatus.COMPLETED,
                LifecycleStatus.FAILED,
                LifecycleStatus.SUSPENDED,
            }
        ),
        LifecycleStatus.COMPLETED: frozenset(
            {
                LifecycleStatus.SCHEDULED,
                LifecycleStatus.INACTIVE,
                LifecycleStatus.RETIRED,
            }
        ),
        LifecycleStatus.FAILED: frozenset(
            {
                LifecycleStatus.SCHEDULED,
                LifecycleStatus.INACTIVE,
                LifecycleStatus.SUSPENDED,
                LifecycleStatus.RETIRED,
            }
        ),
        LifecycleStatus.SUSPENDED: frozenset(
            {
                LifecycleStatus.INACTIVE,
                LifecycleStatus.RETIRED,
            }
        ),
        LifecycleStatus.RETIRED: frozenset(),
    }
)


class AgentLifecycleManager:
    """Thread-safe in-memory lifecycle registry for known agent identities."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, LifecycleRecord] = {
            agent.agent_id: LifecycleRecord(
                agent_id=agent.agent_id,
                status=LifecycleStatus.REGISTERED,
                revision=0,
                version=LIFECYCLE_VERSION,
            )
            for agent in AGENTS
        }

    def get_state(self, agent_id: str) -> LifecycleRecord:
        """Return the current immutable lifecycle record."""
        with self._lock:
            try:
                return self._records[agent_id]
            except KeyError as exc:
                raise UnknownAgentError(
                    f"Unknown agent identity: {agent_id}"
                ) from exc

    def transition(
        self,
        agent_id: str,
        target: LifecycleStatus,
        expected_revision: int | None = None,
    ) -> LifecycleRecord:
        """Apply one allowed transition with optional revision checking."""

        if not isinstance(target, LifecycleStatus):
            raise LifecycleError("target must be a LifecycleStatus value.")

        with self._lock:
            current = self.get_state(agent_id)

            if expected_revision is not None:
                if (
                    isinstance(expected_revision, bool)
                    or not isinstance(expected_revision, int)
                    or expected_revision < 0
                ):
                    raise LifecycleError(
                        "expected_revision must be a non-negative integer."
                    )

                if current.revision != expected_revision:
                    raise RevisionConflictError(
                        f"Expected revision {expected_revision}, "
                        f"found {current.revision}."
                    )

            # Repeating the current desired state is an idempotent no-op.
            # It does not create a new revision or lifecycle event.
            if target == current.status:
                return current

            allowed = _ALLOWED_TRANSITIONS[current.status]

            if target not in allowed:
                raise InvalidTransitionError(
                    f"Transition from {current.status.value} "
                    f"to {target.value} is not allowed."
                )

            updated = LifecycleRecord(
                agent_id=agent_id,
                status=target,
                revision=current.revision + 1,
                version=LIFECYCLE_VERSION,
            )

            self._records[agent_id] = updated
            return updated

    def snapshot(self) -> Mapping[str, LifecycleRecord]:
        """Return an immutable snapshot of all lifecycle records."""
        with self._lock:
            return MappingProxyType(dict(self._records))


def validate_lifecycle_contract() -> bool:
    """Validate transition definitions and terminal-state behavior."""

    if set(_ALLOWED_TRANSITIONS) != set(LifecycleStatus):
        raise LifecycleError("Every lifecycle state must have a transition rule.")

    for source, targets in _ALLOWED_TRANSITIONS.items():
        if not isinstance(targets, frozenset):
            raise LifecycleError("Transition targets must be immutable.")

        if source in targets:
            raise LifecycleError("Self-transitions are not permitted.")

    if _ALLOWED_TRANSITIONS[LifecycleStatus.RETIRED]:
        raise LifecycleError("Retired must be a terminal state.")

    return True


validate_lifecycle_contract()
