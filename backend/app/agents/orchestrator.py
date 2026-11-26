"""Simulation-only orchestration for CYVANTA FORTRESS V2."""

from dataclasses import dataclass
from enum import Enum
from threading import RLock
from types import MappingProxyType
from typing import Mapping

from app.agents.identity import get_agent
from app.agents.lifecycle import (
    AgentLifecycleManager,
    LifecycleError,
    LifecycleStatus,
)
from app.agents.message_contract import (
    MessageProposal,
    validate_message,
)
from app.agents.permissions import (
    AgentPermission,
    evaluate_permission,
)
from app.agents.task_contract import (
    TaskContract,
    TaskProposal,
    validate_task_delegation,
)


ORCHESTRATOR_VERSION = "2.0.0"
DEFAULT_MAX_CONCURRENT_TASKS = 3
DEFAULT_MAX_PENDING_TASKS = 50


class OrchestrationStatus(str, Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OrchestrationRecord:
    task: TaskContract
    status: OrchestrationStatus
    revision: int
    version: str = ORCHESTRATOR_VERSION


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    allowed: bool
    reason: str
    record: OrchestrationRecord | None = None
    version: str = ORCHESTRATOR_VERSION


@dataclass(frozen=True, slots=True)
class MessageCoordinationResult:
    allowed: bool
    reason: str
    message: object | None = None
    version: str = ORCHESTRATOR_VERSION


class AgentOrchestrator:
    """Coordinates advisory tasks without launching agent processes."""

    def __init__(
        self,
        lifecycle_manager: AgentLifecycleManager | None = None,
        *,
        max_concurrent_tasks: int = DEFAULT_MAX_CONCURRENT_TASKS,
        max_pending_tasks: int = DEFAULT_MAX_PENDING_TASKS,
    ) -> None:
        for name, value in (
            ("max_concurrent_tasks", max_concurrent_tasks),
            ("max_pending_tasks", max_pending_tasks),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")

        self._lock = RLock()
        self._lifecycle = lifecycle_manager or AgentLifecycleManager()
        self._max_concurrent = max_concurrent_tasks
        self._max_pending = max_pending_tasks
        self._records: dict[str, OrchestrationRecord] = {}
        self._seen_message_ids: set[str] = set()
        self._active_count = 0

    @property
    def max_concurrent_tasks(self) -> int:
        return self._max_concurrent

    @property
    def max_pending_tasks(self) -> int:
        return self._max_pending

    def submit_task(self, proposal: TaskProposal) -> OrchestrationResult:
        """Validate and schedule one advisory task; never execute it."""
        with self._lock:
            if not isinstance(proposal, TaskProposal):
                return OrchestrationResult(False, "Invalid task proposal.")

            validation = validate_task_delegation(proposal)
            if not validation.allowed or validation.task is None:
                return OrchestrationResult(False, validation.reason)

            task = validation.task

            # Check the normalized contract ID, not untrusted proposal text.
            if task.task_id in self._records:
                return OrchestrationResult(False, "Duplicate task ID.")

            pending = sum(
                record.status == OrchestrationStatus.SCHEDULED
                for record in self._records.values()
            )
            if pending >= self._max_pending:
                return OrchestrationResult(False, "Pending task capacity reached.")

            try:
                agent = get_agent(task.assigned_to)
                permission = evaluate_permission(
                    agent.agent_id,
                    AgentPermission.READ_AGENT_METADATA,
                )
                if not permission.allowed:
                    return OrchestrationResult(False, permission.reason)

                lifecycle = self._lifecycle.get_state(agent.agent_id)
                if lifecycle.status not in (
                    LifecycleStatus.REGISTERED,
                    LifecycleStatus.INACTIVE,
                    LifecycleStatus.COMPLETED,
                    LifecycleStatus.FAILED,
                ):
                    return OrchestrationResult(
                        False,
                        "Assigned agent is not available for scheduling.",
                    )

                self._lifecycle.transition(
                    agent.agent_id,
                    LifecycleStatus.SCHEDULED,
                    expected_revision=lifecycle.revision,
                )
            except (LifecycleError, KeyError, ValueError, TypeError) as exc:
                return OrchestrationResult(
                    False,
                    f"Scheduling rejected: {exc}",
                )

            record = OrchestrationRecord(
                task=task,
                status=OrchestrationStatus.SCHEDULED,
                revision=0,
            )
            self._records[task.task_id] = record

            return OrchestrationResult(
                True,
                "Task validated and scheduled for simulation.",
                record,
            )

    def start_simulation(self, task_id: str) -> OrchestrationResult:
        """Mark a scheduled task as running without starting a process."""
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return OrchestrationResult(False, "Unknown task ID.")

            if record.status != OrchestrationStatus.SCHEDULED:
                return OrchestrationResult(
                    False,
                    "Only scheduled tasks can enter simulation.",
                    record,
                )

            if self._active_count >= self._max_concurrent:
                return OrchestrationResult(
                    False,
                    "Concurrent simulation capacity reached.",
                    record,
                )

            agent_id = record.task.assigned_to

            try:
                lifecycle = self._lifecycle.get_state(agent_id)
                self._lifecycle.transition(
                    agent_id,
                    LifecycleStatus.RUNNING,
                    expected_revision=lifecycle.revision,
                )
            except (LifecycleError, KeyError, ValueError, TypeError) as exc:
                return OrchestrationResult(
                    False,
                    f"Simulation start rejected: {exc}",
                    record,
                )

            updated = OrchestrationRecord(
                task=record.task,
                status=OrchestrationStatus.RUNNING,
                revision=record.revision + 1,
            )
            self._records[task_id] = updated
            self._active_count += 1

            return OrchestrationResult(
                True,
                "Simulation state started. No agent process was launched.",
                updated,
            )

    def finish_simulation(
        self,
        task_id: str,
        *,
        succeeded: bool,
    ) -> OrchestrationResult:
        """Record a simulated outcome and release the concurrency slot."""
        if not isinstance(succeeded, bool):
            return OrchestrationResult(
                False,
                "succeeded must be a boolean value.",
            )

        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return OrchestrationResult(False, "Unknown task ID.")

            if record.status != OrchestrationStatus.RUNNING:
                return OrchestrationResult(
                    False,
                    "Only running simulations can be completed.",
                    record,
                )

            target = (
                LifecycleStatus.COMPLETED
                if succeeded
                else LifecycleStatus.FAILED
            )
            final_status = (
                OrchestrationStatus.COMPLETED
                if succeeded
                else OrchestrationStatus.FAILED
            )

            try:
                lifecycle = self._lifecycle.get_state(
                    record.task.assigned_to
                )
                self._lifecycle.transition(
                    record.task.assigned_to,
                    target,
                    expected_revision=lifecycle.revision,
                )
            except (LifecycleError, KeyError, ValueError, TypeError) as exc:
                return OrchestrationResult(
                    False,
                    f"Simulation completion rejected: {exc}",
                    record,
                )

            updated = OrchestrationRecord(
                task=record.task,
                status=final_status,
                revision=record.revision + 1,
            )
            self._records[task_id] = updated
            self._active_count -= 1

            return OrchestrationResult(
                True,
                "Simulated outcome recorded. No external action occurred.",
                updated,
            )

    def coordinate_message(
        self,
        proposal: MessageProposal,
    ) -> MessageCoordinationResult:
        """Validate an advisory message without delivering or persisting it."""
        with self._lock:
            result = validate_message(
                proposal,
                seen_message_ids=self._seen_message_ids,
            )
            if not result.allowed or result.message is None:
                return MessageCoordinationResult(
                    False,
                    result.reason,
                )

            self._seen_message_ids.add(result.message.message_id)
            return MessageCoordinationResult(
                True,
                "Message validated for coordination; it was not delivered.",
                result.message,
            )

    def get_task(self, task_id: str) -> OrchestrationRecord | None:
        with self._lock:
            return self._records.get(task_id)

    def snapshot(self) -> Mapping[str, OrchestrationRecord]:
        with self._lock:
            return MappingProxyType(dict(self._records))

    def get_capacity(self) -> Mapping[str, int]:
        with self._lock:
            pending = sum(
                record.status == OrchestrationStatus.SCHEDULED
                for record in self._records.values()
            )
            return MappingProxyType({
                "max_concurrent": self._max_concurrent,
                "active": self._active_count,
                "available": self._max_concurrent - self._active_count,
                "max_pending": self._max_pending,
                "pending": pending,
            })


def validate_orchestrator_contract() -> bool:
    """Check the orchestrator's static safety boundaries."""
    return (
        ORCHESTRATOR_VERSION == "2.0.0"
        and DEFAULT_MAX_CONCURRENT_TASKS >= 1
        and DEFAULT_MAX_PENDING_TASKS >= 1
        and len(AgentOrchestrator().snapshot()) == 0
    )
