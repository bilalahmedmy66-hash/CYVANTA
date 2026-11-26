import pytest

from app.agents.identity import AGENTS, AgentType
from app.agents.lifecycle import AgentLifecycleManager, LifecycleStatus
from app.agents.message_contract import MessageProposal
from app.agents.task_contract import AdvisoryTaskType, TaskProposal

from app.agents.orchestrator import (
    AgentOrchestrator,
    OrchestrationStatus,
    validate_orchestrator_contract,
)


GLOBAL = next(
    agent for agent in AGENTS
    if agent.agent_type == AgentType.GLOBAL_COORDINATOR
)
LAYERS = [
    agent for agent in AGENTS
    if agent.agent_type == AgentType.LAYER_COORDINATOR
]

ORG = "org-orchestrator-test"
TENANT = "tenant-orchestrator-test"
TIMESTAMP = "2026-11-24T10:00:00+05:30"


def make_task(receiver, **overrides):
    values = {
        "task_id": "orchestrator-task-001",
        "assigned_by": GLOBAL.agent_id,
        "assigned_to": receiver.agent_id,
        "task_type": AdvisoryTaskType.ANALYZE.value,
        "objective": "Analyze supplied synthetic evidence",
        "organization_id": ORG,
        "tenant_id": TENANT,
    }
    values.update(overrides)
    return TaskProposal(**values)


def make_message(receiver, **overrides):
    values = {
        "message_id": "orchestrator-message-001",
        "sender_agent_id": GLOBAL.agent_id,
        "receiver_agent_id": receiver.agent_id,
        "message_type": "status_update",
        "organization_id": ORG,
        "tenant_id": TENANT,
        "correlation_id": "orchestrator-correlation-001",
        "created_at": TIMESTAMP,
        "payload": {"summary": "Synthetic status update"},
    }
    values.update(overrides)
    return MessageProposal(**values)


def test_static_orchestrator_contract_is_valid():
    assert validate_orchestrator_contract() is True


def test_orchestrator_starts_with_empty_task_registry():
    orchestrator = AgentOrchestrator()

    assert len(orchestrator.snapshot()) == 0
    assert orchestrator.get_capacity()["active"] == 0


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2"])
def test_invalid_capacity_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        AgentOrchestrator(max_concurrent_tasks=value)


def test_valid_task_is_scheduled_without_execution():
    lifecycle = AgentLifecycleManager()
    orchestrator = AgentOrchestrator(lifecycle)

    result = orchestrator.submit_task(make_task(LAYERS[0]))

    assert result.allowed is True
    assert result.record.status == OrchestrationStatus.SCHEDULED
    assert result.record.task.assigned_to == LAYERS[0].agent_id
    assert lifecycle.get_state(LAYERS[0].agent_id).status == LifecycleStatus.SCHEDULED


def test_duplicate_task_id_is_rejected():
    orchestrator = AgentOrchestrator()

    first = orchestrator.submit_task(make_task(LAYERS[0]))
    second = orchestrator.submit_task(
        make_task(LAYERS[1], task_id="orchestrator-task-001")
    )

    assert first.allowed is True
    assert second.allowed is False
    assert "Duplicate" in second.reason
    assert len(orchestrator.snapshot()) == 1


def test_task_id_is_normalized_before_duplicate_check():
    orchestrator = AgentOrchestrator()

    first = orchestrator.submit_task(
        make_task(LAYERS[0], task_id="  normalized-task  ")
    )
    second = orchestrator.submit_task(
        make_task(LAYERS[1], task_id="normalized-task")
    )

    assert first.allowed is True
    assert first.record.task.task_id == "normalized-task"
    assert second.allowed is False
    assert len(orchestrator.snapshot()) == 1


def test_invalid_delegation_is_rejected():
    orchestrator = AgentOrchestrator()

    result = orchestrator.submit_task(
        make_task(LAYERS[0], assigned_to="UNKNOWN-AGENT")
    )

    assert result.allowed is False
    assert len(orchestrator.snapshot()) == 0


def test_simulation_lifecycle_completes_successfully():
    lifecycle = AgentLifecycleManager()
    orchestrator = AgentOrchestrator(lifecycle)
    agent_id = LAYERS[0].agent_id

    scheduled = orchestrator.submit_task(make_task(LAYERS[0]))
    started = orchestrator.start_simulation(scheduled.record.task.task_id)
    finished = orchestrator.finish_simulation(
        scheduled.record.task.task_id,
        succeeded=True,
    )

    assert scheduled.allowed is True
    assert started.allowed is True
    assert started.record.status == OrchestrationStatus.RUNNING
    assert finished.allowed is True
    assert finished.record.status == OrchestrationStatus.COMPLETED
    assert lifecycle.get_state(agent_id).status == LifecycleStatus.COMPLETED
    assert orchestrator.get_capacity()["active"] == 0


def test_simulated_failure_updates_lifecycle():
    lifecycle = AgentLifecycleManager()
    orchestrator = AgentOrchestrator(lifecycle)

    scheduled = orchestrator.submit_task(make_task(LAYERS[0]))
    started = orchestrator.start_simulation(scheduled.record.task.task_id)
    finished = orchestrator.finish_simulation(
        scheduled.record.task.task_id,
        succeeded=False,
    )

    assert started.allowed is True
    assert finished.allowed is True
    assert finished.record.status == OrchestrationStatus.FAILED
    assert lifecycle.get_state(LAYERS[0].agent_id).status == LifecycleStatus.FAILED


def test_concurrent_simulation_limit_is_enforced():
    orchestrator = AgentOrchestrator(max_concurrent_tasks=1)

    first = orchestrator.submit_task(make_task(LAYERS[0], task_id="task-a"))
    second = orchestrator.submit_task(make_task(LAYERS[1], task_id="task-b"))

    first_start = orchestrator.start_simulation("task-a")
    second_start = orchestrator.start_simulation("task-b")

    assert first.allowed is True
    assert second.allowed is True
    assert first_start.allowed is True
    assert second_start.allowed is False
    assert orchestrator.get_capacity()["active"] == 1


def test_capacity_is_released_after_simulation_finishes():
    orchestrator = AgentOrchestrator(max_concurrent_tasks=1)

    orchestrator.submit_task(make_task(LAYERS[0], task_id="task-a"))
    orchestrator.submit_task(make_task(LAYERS[1], task_id="task-b"))

    assert orchestrator.start_simulation("task-a").allowed is True
    assert orchestrator.start_simulation("task-b").allowed is False

    assert orchestrator.finish_simulation("task-a", succeeded=True).allowed is True
    assert orchestrator.start_simulation("task-b").allowed is True


def test_pending_task_limit_is_enforced():
    orchestrator = AgentOrchestrator(max_pending_tasks=1)

    first = orchestrator.submit_task(make_task(LAYERS[0], task_id="task-a"))
    second = orchestrator.submit_task(make_task(LAYERS[1], task_id="task-b"))

    assert first.allowed is True
    assert second.allowed is False
    assert "capacity" in second.reason.lower()


def test_unknown_task_cannot_start_or_finish():
    orchestrator = AgentOrchestrator()

    assert orchestrator.start_simulation("missing").allowed is False
    assert orchestrator.finish_simulation(
        "missing",
        succeeded=True,
    ).allowed is False


def test_only_scheduled_task_can_start():
    orchestrator = AgentOrchestrator()

    result = orchestrator.start_simulation("missing")

    assert result.allowed is False


def test_only_running_task_can_finish():
    orchestrator = AgentOrchestrator()
    orchestrator.submit_task(make_task(LAYERS[0]))

    result = orchestrator.finish_simulation(
        "orchestrator-task-001",
        succeeded=True,
    )

    assert result.allowed is False


def test_succeeded_must_be_boolean():
    orchestrator = AgentOrchestrator()

    result = orchestrator.finish_simulation(
        "missing",
        succeeded=1,
    )

    assert result.allowed is False


def test_message_is_validated_but_not_delivered():
    orchestrator = AgentOrchestrator()

    result = orchestrator.coordinate_message(make_message(LAYERS[0]))

    assert result.allowed is True
    assert result.message.message_id == "orchestrator-message-001"


def test_duplicate_message_id_is_rejected():
    orchestrator = AgentOrchestrator()
    proposal = make_message(LAYERS[0])

    first = orchestrator.coordinate_message(proposal)
    second = orchestrator.coordinate_message(proposal)

    assert first.allowed is True
    assert second.allowed is False


def test_invalid_message_route_is_rejected():
    orchestrator = AgentOrchestrator()

    result = orchestrator.coordinate_message(
        make_message(LAYERS[1], sender_agent_id=LAYERS[0].agent_id)
    )

    assert result.allowed is False


def test_snapshot_is_immutable():
    orchestrator = AgentOrchestrator()
    orchestrator.submit_task(make_task(LAYERS[0]))

    snapshot = orchestrator.snapshot()

    with pytest.raises(TypeError):
        snapshot["injected"] = snapshot["orchestrator-task-001"]


def test_task_record_is_not_mutated_by_failed_start():
    orchestrator = AgentOrchestrator()
    orchestrator.submit_task(make_task(LAYERS[0]))

    before = orchestrator.get_task("orchestrator-task-001")
    result = orchestrator.start_simulation("unknown-task")
    after = orchestrator.get_task("orchestrator-task-001")

    assert result.allowed is False
    assert before == after

