from dataclasses import FrozenInstanceError

import pytest

from app.agents.identity import (
    AGENT_CONTRACT_VERSION,
    AGENTS,
    AGENTS_BY_ID,
    AGENTS_BY_LAYER,
    ADVISORY_CAPABILITIES,
    EXPECTED_AGENT_COUNT,
    SPECIALISTS_PER_LAYER,
    AgentType,
    get_agent,
    get_agents_for_layer,
    validate_agent_registry,
)
from app.fortress.registry import LAYERS


def test_registry_contains_exactly_211_agents():
    assert len(AGENTS) == 211
    assert len(AGENTS) == EXPECTED_AGENT_COUNT


def test_registry_has_expected_agent_type_counts():
    assert sum(
        agent.agent_type == AgentType.GLOBAL_COORDINATOR
        for agent in AGENTS
    ) == 1

    assert sum(
        agent.agent_type == AgentType.LAYER_COORDINATOR
        for agent in AGENTS
    ) == 10

    assert sum(
        agent.agent_type == AgentType.SPECIALIST
        for agent in AGENTS
    ) == 200


def test_agent_ids_are_unique():
    ids = [agent.agent_id for agent in AGENTS]
    assert len(ids) == len(set(ids))
    assert len(AGENTS_BY_ID) == len(AGENTS)


def test_all_ten_v1_layers_have_v2_agent_assignments():
    assert set(AGENTS_BY_LAYER) == {
        layer.layer_id for layer in LAYERS
    }


@pytest.mark.parametrize(
    "layer",
    LAYERS,
    ids=[layer.layer_id for layer in LAYERS],
)
def test_each_layer_has_one_coordinator_and_twenty_specialists(layer):
    agents = get_agents_for_layer(layer.layer_id)

    assert sum(
        agent.agent_type == AgentType.LAYER_COORDINATOR
        for agent in agents
    ) == 1

    assert sum(
        agent.agent_type == AgentType.SPECIALIST
        for agent in agents
    ) == SPECIALISTS_PER_LAYER


def test_global_coordinator_has_no_parent():
    agent = get_agent("CYV-GLOBAL-COORD-001")

    assert agent.agent_type == AgentType.GLOBAL_COORDINATOR
    assert agent.coordinator_id is None
    assert agent.layer_id is None


def test_layer_coordinator_reports_to_global_coordinator():
    agent = get_agent("CYV-L01-COORD-001")

    assert agent.agent_type == AgentType.LAYER_COORDINATOR
    assert agent.coordinator_id == "CYV-GLOBAL-COORD-001"


def test_specialist_reports_to_its_layer_coordinator():
    agent = get_agent("CYV-L01-SP-001")

    assert agent.agent_type == AgentType.SPECIALIST
    assert agent.coordinator_id == "CYV-L01-COORD-001"


def test_agent_lookup_returns_registered_identity():
    agent = AGENTS[0]
    assert get_agent(agent.agent_id) is agent


def test_unknown_agent_lookup_raises_key_error():
    with pytest.raises(KeyError):
        get_agent("UNKNOWN-AGENT")


def test_unknown_layer_lookup_raises_key_error():
    with pytest.raises(KeyError):
        get_agents_for_layer("unknown_layer")


def test_agent_identity_is_immutable():
    with pytest.raises(FrozenInstanceError):
        AGENTS[0].role = "Unauthorized role"


def test_registry_mappings_are_immutable():
    with pytest.raises(TypeError):
        AGENTS_BY_ID["UNAUTHORIZED"] = AGENTS[0]

    with pytest.raises(TypeError):
        AGENTS_BY_LAYER["unauthorized"] = ()


def test_all_agents_have_required_metadata():
    for agent in AGENTS:
        assert agent.agent_id
        assert agent.role
        assert agent.responsibility
        assert agent.memory_namespace
        assert agent.contract_version == AGENT_CONTRACT_VERSION
        assert agent.status == "registered"


def test_all_initial_agents_are_advisory_only():
    for agent in AGENTS:
        assert agent.permission_profile == "advisory_only"
        assert agent.capabilities == ADVISORY_CAPABILITIES
        assert "execute" not in agent.capabilities


def test_specialists_have_individual_memory_namespaces():
    specialists = [
        agent for agent in AGENTS
        if agent.agent_type == AgentType.SPECIALIST
    ]

    namespaces = [agent.memory_namespace for agent in specialists]

    assert len(namespaces) == 200
    assert len(set(namespaces)) == 200


def test_registry_validation_succeeds():
    assert validate_agent_registry() is True


def test_registry_definitions_contain_no_execution_interfaces():
    forbidden_fields = {
        "execute",
        "execute_action",
        "shell_command",
        "network_target",
        "remediation_action",
        "worker_dispatch",
    }

    for agent in AGENTS:
        assert not forbidden_fields.intersection(
            agent.__dataclass_fields__
        )
