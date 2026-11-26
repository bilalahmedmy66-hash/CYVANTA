from dataclasses import FrozenInstanceError

import pytest

from app.agents.control_mapping import (
    CONTROL_MAPPING_VERSION,
    CONTROL_MAPPINGS,
    CONTROL_MAPPINGS_BY_ID,
    CONTROL_MAPPINGS_BY_LAYER,
    ControlAgentMapping,
    get_control_agent_mapping,
    get_control_mappings_for_layer,
    validate_control_mappings,
)
from app.agents.identity import AgentType, get_agents_for_layer
from app.fortress.registry import (
    CONTROLS,
    LAYERS,
    REGISTRY_VERSION,
)


def test_exactly_100_controls_are_mapped():
    assert len(CONTROL_MAPPINGS) == 100
    assert len(CONTROL_MAPPINGS_BY_ID) == 100


def test_every_v1_control_has_one_mapping():
    assert set(CONTROL_MAPPINGS_BY_ID) == {
        control.control_id for control in CONTROLS
    }


def test_all_ten_layers_have_mapping_entries():
    assert set(CONTROL_MAPPINGS_BY_LAYER) == {
        layer.layer_id for layer in LAYERS
    }


@pytest.mark.parametrize(
    "layer",
    LAYERS,
    ids=[layer.layer_id for layer in LAYERS],
)
def test_each_layer_maps_exactly_ten_controls(layer):
    assert len(get_control_mappings_for_layer(layer.layer_id)) == 10


@pytest.mark.parametrize(
    "control",
    CONTROLS,
    ids=[control.control_id for control in CONTROLS],
)
def test_each_control_maps_to_its_own_layer_coordinator(control):
    mapping = get_control_agent_mapping(control.control_id)
    agents = get_agents_for_layer(control.layer_id)

    coordinators = [
        agent for agent in agents
        if agent.agent_type == AgentType.LAYER_COORDINATOR
    ]

    assert len(coordinators) == 1
    assert mapping.coordinator_id == coordinators[0].agent_id


@pytest.mark.parametrize(
    "control",
    CONTROLS,
    ids=[control.control_id for control in CONTROLS],
)
def test_each_control_maps_to_twenty_same_layer_specialists(control):
    mapping = get_control_agent_mapping(control.control_id)
    agents = get_agents_for_layer(control.layer_id)

    expected = tuple(
        agent.agent_id for agent in agents
        if agent.agent_type == AgentType.SPECIALIST
    )

    assert len(mapping.eligible_specialist_ids) == 20
    assert mapping.eligible_specialist_ids == expected


def test_mapping_preserves_v1_registry_version():
    assert all(
        mapping.registry_version == REGISTRY_VERSION
        for mapping in CONTROL_MAPPINGS
    )


def test_mapping_uses_independent_v2_version():
    assert CONTROL_MAPPING_VERSION == "2.0.0"
    assert all(
        mapping.mapping_version == CONTROL_MAPPING_VERSION
        for mapping in CONTROL_MAPPINGS
    )


def test_mapping_preserves_control_layer_and_vault():
    for control in CONTROLS:
        mapping = get_control_agent_mapping(control.control_id)

        assert mapping.layer_id == control.layer_id
        assert mapping.layer_name == control.layer_name
        assert mapping.vault_id == control.vault_id


def test_mapping_records_are_immutable():
    mapping = CONTROL_MAPPINGS[0]

    with pytest.raises(FrozenInstanceError):
        mapping.control_id = "MODIFIED"


def test_mapping_lookup_is_stable():
    mapping = CONTROL_MAPPINGS[0]

    assert get_control_agent_mapping(mapping.control_id) is mapping


def test_unknown_control_id_is_rejected():
    with pytest.raises(KeyError):
        get_control_agent_mapping("UNKNOWN-999")


def test_unknown_layer_id_is_rejected():
    with pytest.raises(KeyError):
        get_control_mappings_for_layer("unknown_layer")


def test_mapping_collections_are_immutable():
    with pytest.raises(TypeError):
        CONTROL_MAPPINGS_BY_ID["UNKNOWN"] = CONTROL_MAPPINGS[0]

    with pytest.raises(TypeError):
        CONTROL_MAPPINGS_BY_LAYER["unknown_layer"] = ()


def test_mapping_validation_passes():
    assert validate_control_mappings() is True


def test_mapping_record_has_expected_structure():
    mapping = CONTROL_MAPPINGS[0]

    assert isinstance(mapping, ControlAgentMapping)
    assert mapping.control_id
    assert mapping.layer_id
    assert mapping.coordinator_id
    assert isinstance(mapping.eligible_specialist_ids, tuple)