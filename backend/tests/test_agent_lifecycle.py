from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from app.agents.identity import AGENTS
from app.agents.lifecycle import (
    LIFECYCLE_VERSION,
    AgentLifecycleManager,
    InvalidTransitionError,
    LifecycleError,
    LifecycleStatus,
    RevisionConflictError,
    UnknownAgentError,
    validate_lifecycle_contract,
)


@pytest.fixture
def manager():
    return AgentLifecycleManager()


def test_all_registered_agents_receive_initial_lifecycle_records(manager):
    snapshot = manager.snapshot()

    assert len(snapshot) == len(AGENTS) == 211
    assert all(
        record.status == LifecycleStatus.REGISTERED
        for record in snapshot.values()
    )


def test_initial_record_has_revision_zero_and_contract_version(manager):
    record = manager.get_state("CYV-GLOBAL-COORD-001")

    assert record.revision == 0
    assert record.version == LIFECYCLE_VERSION


def test_unknown_agent_is_rejected(manager):
    with pytest.raises(UnknownAgentError):
        manager.get_state("UNKNOWN-AGENT")


def test_unknown_agent_transition_is_rejected(manager):
    with pytest.raises(UnknownAgentError):
        manager.transition("UNKNOWN-AGENT", LifecycleStatus.INACTIVE)


@pytest.mark.parametrize(
    "source,target",
    [
        (LifecycleStatus.REGISTERED, LifecycleStatus.INACTIVE),
        (LifecycleStatus.REGISTERED, LifecycleStatus.SCHEDULED),
        (LifecycleStatus.REGISTERED, LifecycleStatus.SUSPENDED),
        (LifecycleStatus.REGISTERED, LifecycleStatus.RETIRED),
        (LifecycleStatus.INACTIVE, LifecycleStatus.SCHEDULED),
        (LifecycleStatus.INACTIVE, LifecycleStatus.SUSPENDED),
        (LifecycleStatus.INACTIVE, LifecycleStatus.RETIRED),
        (LifecycleStatus.SCHEDULED, LifecycleStatus.RUNNING),
        (LifecycleStatus.SCHEDULED, LifecycleStatus.INACTIVE),
        (LifecycleStatus.SCHEDULED, LifecycleStatus.FAILED),
        (LifecycleStatus.SCHEDULED, LifecycleStatus.SUSPENDED),
        (LifecycleStatus.RUNNING, LifecycleStatus.COMPLETED),
        (LifecycleStatus.RUNNING, LifecycleStatus.FAILED),
        (LifecycleStatus.RUNNING, LifecycleStatus.SUSPENDED),
        (LifecycleStatus.COMPLETED, LifecycleStatus.SCHEDULED),
        (LifecycleStatus.COMPLETED, LifecycleStatus.INACTIVE),
        (LifecycleStatus.COMPLETED, LifecycleStatus.RETIRED),
        (LifecycleStatus.FAILED, LifecycleStatus.SCHEDULED),
        (LifecycleStatus.FAILED, LifecycleStatus.INACTIVE),
        (LifecycleStatus.FAILED, LifecycleStatus.SUSPENDED),
        (LifecycleStatus.FAILED, LifecycleStatus.RETIRED),
        (LifecycleStatus.SUSPENDED, LifecycleStatus.INACTIVE),
        (LifecycleStatus.SUSPENDED, LifecycleStatus.RETIRED),
    ],
)
def test_every_allowed_transition_succeeds(manager, source, target):
    agent_id = "CYV-GLOBAL-COORD-001"

    paths = {
        LifecycleStatus.REGISTERED: [],
        LifecycleStatus.INACTIVE: [
            LifecycleStatus.INACTIVE,
        ],
        LifecycleStatus.SCHEDULED: [
            LifecycleStatus.SCHEDULED,
        ],
        LifecycleStatus.RUNNING: [
            LifecycleStatus.SCHEDULED,
            LifecycleStatus.RUNNING,
        ],
        LifecycleStatus.COMPLETED: [
            LifecycleStatus.SCHEDULED,
            LifecycleStatus.RUNNING,
            LifecycleStatus.COMPLETED,
        ],
        LifecycleStatus.FAILED: [
            LifecycleStatus.SCHEDULED,
            LifecycleStatus.FAILED,
        ],
        LifecycleStatus.SUSPENDED: [
            LifecycleStatus.SUSPENDED,
        ],
        LifecycleStatus.RETIRED: [
            LifecycleStatus.RETIRED,
        ],
    }

    for step in paths[source]:
        manager.transition(agent_id, step)

    assert manager.get_state(agent_id).status == source

    updated = manager.transition(agent_id, target)

    assert updated.status == target
    assert updated.revision == manager.get_state(agent_id).revision


@pytest.mark.parametrize(
    "source,target",
    [
        (LifecycleStatus.REGISTERED, LifecycleStatus.RUNNING),
        (LifecycleStatus.INACTIVE, LifecycleStatus.RUNNING),
        (LifecycleStatus.SCHEDULED, LifecycleStatus.COMPLETED),
        (LifecycleStatus.RUNNING, LifecycleStatus.SCHEDULED),
        (LifecycleStatus.SUSPENDED, LifecycleStatus.RUNNING),
        (LifecycleStatus.RETIRED, LifecycleStatus.REGISTERED),
        (LifecycleStatus.RETIRED, LifecycleStatus.SCHEDULED),
    ],
)
def test_prohibited_transitions_are_rejected(manager, source, target):
    agent_id = "CYV-GLOBAL-COORD-001"

    if source == LifecycleStatus.INACTIVE:
        manager.transition(agent_id, LifecycleStatus.INACTIVE)
    elif source == LifecycleStatus.SCHEDULED:
        manager.transition(agent_id, LifecycleStatus.SCHEDULED)
    elif source == LifecycleStatus.RUNNING:
        manager.transition(agent_id, LifecycleStatus.SCHEDULED)
        manager.transition(agent_id, LifecycleStatus.RUNNING)
    elif source == LifecycleStatus.SUSPENDED:
        manager.transition(agent_id, LifecycleStatus.SUSPENDED)
    elif source == LifecycleStatus.RETIRED:
        manager.transition(agent_id, LifecycleStatus.RETIRED)

    with pytest.raises(InvalidTransitionError):
        manager.transition(agent_id, target)


def test_revision_increments_after_each_transition(manager):
    agent_id = "CYV-GLOBAL-COORD-001"

    first = manager.transition(agent_id, LifecycleStatus.SCHEDULED)
    second = manager.transition(
        agent_id,
        LifecycleStatus.RUNNING,
        expected_revision=first.revision,
    )

    assert first.revision == 1
    assert second.revision == 2


def test_stale_revision_is_rejected_without_mutation(manager):
    agent_id = "CYV-GLOBAL-COORD-001"
    manager.transition(agent_id, LifecycleStatus.SCHEDULED)

    with pytest.raises(RevisionConflictError):
        manager.transition(
            agent_id,
            LifecycleStatus.RUNNING,
            expected_revision=0,
        )

    assert manager.get_state(agent_id).status == LifecycleStatus.SCHEDULED
    assert manager.get_state(agent_id).revision == 1


@pytest.mark.parametrize("revision", [-1, True, 1.5, "1"])
def test_invalid_revision_values_are_rejected(manager, revision):
    with pytest.raises(LifecycleError):
        manager.transition(
            "CYV-GLOBAL-COORD-001",
            LifecycleStatus.SCHEDULED,
            expected_revision=revision,
        )


def test_invalid_target_type_is_rejected(manager):
    with pytest.raises(LifecycleError):
        manager.transition("CYV-GLOBAL-COORD-001", "running")


def test_lifecycle_records_are_immutable(manager):
    record = manager.get_state("CYV-GLOBAL-COORD-001")

    with pytest.raises(FrozenInstanceError):
        record.status = LifecycleStatus.RUNNING


def test_snapshot_is_immutable(manager):
    snapshot = manager.snapshot()

    with pytest.raises(TypeError):
        snapshot["UNAUTHORIZED"] = snapshot["CYV-GLOBAL-COORD-001"]


def test_retired_agent_cannot_be_reactivated(manager):
    agent_id = "CYV-GLOBAL-COORD-001"
    manager.transition(agent_id, LifecycleStatus.RETIRED)

    with pytest.raises(InvalidTransitionError):
        manager.transition(agent_id, LifecycleStatus.REGISTERED)


def test_lifecycle_contract_is_valid():
    assert validate_lifecycle_contract() is True


def test_repeated_same_state_transition_is_idempotent(manager):
    agent_id = "CYV-GLOBAL-COORD-001"

    first = manager.transition(agent_id, LifecycleStatus.INACTIVE)
    second = manager.transition(agent_id, LifecycleStatus.INACTIVE)

    assert first == second
    assert second.revision == 1


def test_concurrent_same_state_requests_are_idempotent(manager):
    agent_id = "CYV-GLOBAL-COORD-001"

    def move_to_inactive(_):
        return manager.transition(agent_id, LifecycleStatus.INACTIVE)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(move_to_inactive, range(8)))

    final_record = manager.get_state(agent_id)

    assert len(results) == 8
    assert all(result == final_record for result in results)
    assert final_record.status == LifecycleStatus.INACTIVE
    assert final_record.revision == 1
