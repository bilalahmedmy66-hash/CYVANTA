"""Read-only mapping between V1 security controls and V2 advisory agents."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.agents.identity import AgentType, get_agents_for_layer
from app.fortress.registry import (
    CONTROLS,
    CONTROLS_BY_ID,
    LAYERS,
    REGISTRY_VERSION,
)

CONTROL_MAPPING_VERSION = "2.0.0"


@dataclass(frozen=True, slots=True)
class ControlAgentMapping:
    """Immutable eligibility mapping for one V1 security control."""

    control_id: str
    layer_id: str
    layer_name: str
    vault_id: str
    registry_version: str
    mapping_version: str
    coordinator_id: str
    eligible_specialist_ids: tuple[str, ...]


def _build_control_mappings() -> tuple[ControlAgentMapping, ...]:
    mappings = []

    for control in CONTROLS:
        layer_agents = get_agents_for_layer(control.layer_id)

        coordinators = tuple(
            agent for agent in layer_agents
            if agent.agent_type == AgentType.LAYER_COORDINATOR
        )
        specialists = tuple(
            agent for agent in layer_agents
            if agent.agent_type == AgentType.SPECIALIST
        )

        if len(coordinators) != 1:
            raise ValueError(
                f"Control {control.control_id} must resolve to exactly one layer coordinator."
            )

        if len(specialists) != 20:
            raise ValueError(
                f"Control {control.control_id} must resolve to exactly 20 eligible specialists."
            )

        mappings.append(
            ControlAgentMapping(
                control_id=control.control_id,
                layer_id=control.layer_id,
                layer_name=control.layer_name,
                vault_id=control.vault_id,
                registry_version=REGISTRY_VERSION,
                mapping_version=CONTROL_MAPPING_VERSION,
                coordinator_id=coordinators[0].agent_id,
                eligible_specialist_ids=tuple(
                    agent.agent_id for agent in specialists
                ),
            )
        )

    return tuple(mappings)


CONTROL_MAPPINGS: tuple[ControlAgentMapping, ...] = (
    _build_control_mappings()
)

CONTROL_MAPPINGS_BY_ID: Mapping[str, ControlAgentMapping] = (
    MappingProxyType(
        {mapping.control_id: mapping for mapping in CONTROL_MAPPINGS}
    )
)

CONTROL_MAPPINGS_BY_LAYER: Mapping[
    str, tuple[ControlAgentMapping, ...]
] = MappingProxyType(
    {
        layer.layer_id: tuple(
            mapping for mapping in CONTROL_MAPPINGS
            if mapping.layer_id == layer.layer_id
        )
        for layer in LAYERS
    }
)


def get_control_agent_mapping(control_id: str) -> ControlAgentMapping:
    """Return the immutable agent mapping for a stable V1 control ID."""
    return CONTROL_MAPPINGS_BY_ID[control_id]


def get_control_mappings_for_layer(
    layer_id: str,
) -> tuple[ControlAgentMapping, ...]:
    """Return all control mappings belonging to one V1 layer."""
    return CONTROL_MAPPINGS_BY_LAYER[layer_id]


def validate_control_mappings() -> bool:
    """Validate completeness, version alignment, and layer isolation."""

    if len(CONTROL_MAPPINGS) != 100:
        raise ValueError("V2 must map exactly 100 V1 security controls.")

    if len(CONTROL_MAPPINGS_BY_ID) != 100:
        raise ValueError("Control mapping identifiers must be unique.")

    if set(CONTROL_MAPPINGS_BY_ID) != set(CONTROLS_BY_ID):
        raise ValueError("Every V1 control must have exactly one V2 mapping.")

    if set(CONTROL_MAPPINGS_BY_LAYER) != {
        layer.layer_id for layer in LAYERS
    }:
        raise ValueError("V2 mapping layer identifiers do not match V1.")

    for layer in LAYERS:
        layer_mappings = get_control_mappings_for_layer(layer.layer_id)

        if len(layer_mappings) != 10:
            raise ValueError(
                f"Layer {layer.layer_id} must map exactly 10 controls."
            )

        expected_agents = get_agents_for_layer(layer.layer_id)
        expected_coordinator = tuple(
            agent for agent in expected_agents
            if agent.agent_type == AgentType.LAYER_COORDINATOR
        )
        expected_specialists = tuple(
            agent.agent_id for agent in expected_agents
            if agent.agent_type == AgentType.SPECIALIST
        )

        if len(expected_coordinator) != 1 or len(expected_specialists) != 20:
            raise ValueError(
                f"Layer {layer.layer_id} has an invalid V2 agent registry."
            )

        for mapping in layer_mappings:
            control = CONTROLS_BY_ID[mapping.control_id]

            if mapping.layer_id != layer.layer_id:
                raise ValueError("Control-to-layer mapping mismatch.")

            if control.layer_id != mapping.layer_id:
                raise ValueError("V1 control layer was changed in V2 mapping.")

            if mapping.vault_id != control.vault_id:
                raise ValueError("Control-to-vault mapping mismatch.")

            if mapping.registry_version != REGISTRY_VERSION:
                raise ValueError("V1 registry version mismatch.")

            if mapping.mapping_version != CONTROL_MAPPING_VERSION:
                raise ValueError("V2 mapping version mismatch.")

            if mapping.coordinator_id != expected_coordinator[0].agent_id:
                raise ValueError("Control has an incorrect layer coordinator.")

            if mapping.eligible_specialist_ids != expected_specialists:
                raise ValueError("Control has an invalid specialist eligibility pool.")

    return True


validate_control_mappings()