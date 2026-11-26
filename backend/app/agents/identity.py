"""Immutable logical agent identities for CYVANTA FORTRESS V2.

This module defines identity metadata only. It does not launch agents,
grant permissions, access external systems, or execute security actions.
"""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from app.fortress.registry import LAYERS


AGENT_CONTRACT_VERSION = "2.0.0"
SPECIALISTS_PER_LAYER = 20
EXPECTED_AGENT_COUNT = 211

ADVISORY_CAPABILITIES = ("observe", "analyze", "propose")


class AgentType(str, Enum):
    GLOBAL_COORDINATOR = "global_coordinator"
    LAYER_COORDINATOR = "layer_coordinator"
    SPECIALIST = "specialist"


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    agent_id: str
    agent_type: AgentType
    layer_id: str | None
    layer_name: str | None
    role: str
    responsibility: str
    contract_version: str
    capabilities: tuple[str, ...]
    permission_profile: str
    memory_namespace: str
    coordinator_id: str | None
    status: str


def _build_identities() -> tuple[AgentIdentity, ...]:
    identities = [
        AgentIdentity(
            agent_id="CYV-GLOBAL-COORD-001",
            agent_type=AgentType.GLOBAL_COORDINATOR,
            layer_id=None,
            layer_name=None,
            role="Global Coordinator",
            responsibility=(
                "Coordinate layer-level assurance work and consolidate "
                "advisory findings across the V2 system."
            ),
            contract_version=AGENT_CONTRACT_VERSION,
            capabilities=ADVISORY_CAPABILITIES,
            permission_profile="advisory_only",
            memory_namespace="global",
            coordinator_id=None,
            status="registered",
        )
    ]

    global_id = "CYV-GLOBAL-COORD-001"

    for layer_index, layer in enumerate(LAYERS, start=1):
        layer_code = f"L{layer_index:02d}"
        layer_coordinator_id = f"CYV-{layer_code}-COORD-001"

        identities.append(
            AgentIdentity(
                agent_id=layer_coordinator_id,
                agent_type=AgentType.LAYER_COORDINATOR,
                layer_id=layer.layer_id,
                layer_name=layer.name,
                role=f"{layer.name} Coordinator",
                responsibility=(
                    f"Coordinate advisory assurance work for {layer.name}."
                ),
                contract_version=AGENT_CONTRACT_VERSION,
                capabilities=ADVISORY_CAPABILITIES,
                permission_profile="advisory_only",
                memory_namespace=f"layer:{layer.layer_id}",
                coordinator_id=global_id,
                status="registered",
            )
        )

        for specialist_index in range(1, SPECIALISTS_PER_LAYER + 1):
            agent_id = (
                f"CYV-{layer_code}-SP-{specialist_index:03d}"
            )

            identities.append(
                AgentIdentity(
                    agent_id=agent_id,
                    agent_type=AgentType.SPECIALIST,
                    layer_id=layer.layer_id,
                    layer_name=layer.name,
                    role=(
                        f"{layer.name} Specialist "
                        f"{specialist_index:02d}"
                    ),
                    responsibility=(
                        f"Analyze assigned assurance evidence and prepare "
                        f"advisory findings for {layer.name}."
                    ),
                    contract_version=AGENT_CONTRACT_VERSION,
                    capabilities=ADVISORY_CAPABILITIES,
                    permission_profile="advisory_only",
                    memory_namespace=f"agent:{agent_id}",
                    coordinator_id=layer_coordinator_id,
                    status="registered",
                )
            )

    return tuple(identities)


AGENTS: tuple[AgentIdentity, ...] = _build_identities()

AGENTS_BY_ID: Mapping[str, AgentIdentity] = MappingProxyType(
    {agent.agent_id: agent for agent in AGENTS}
)

AGENTS_BY_LAYER: Mapping[str, tuple[AgentIdentity, ...]] = (
    MappingProxyType(
        {
            layer.layer_id: tuple(
                agent
                for agent in AGENTS
                if agent.layer_id == layer.layer_id
            )
            for layer in LAYERS
        }
    )
)


def get_agent(agent_id: str) -> AgentIdentity:
    """Return an immutable identity by its stable identifier."""
    return AGENTS_BY_ID[agent_id]


def get_agents_for_layer(layer_id: str) -> tuple[AgentIdentity, ...]:
    """Return all coordinator and specialist identities for a layer."""
    return AGENTS_BY_LAYER[layer_id]


def validate_agent_registry() -> bool:
    """Validate identity counts, uniqueness, hierarchy, and boundaries."""

    if len(AGENTS) != EXPECTED_AGENT_COUNT:
        raise ValueError("V2 must contain exactly 211 agent identities.")

    if len(AGENTS_BY_ID) != EXPECTED_AGENT_COUNT:
        raise ValueError("Agent identifiers must be unique.")

    global_agents = tuple(
        agent for agent in AGENTS
        if agent.agent_type == AgentType.GLOBAL_COORDINATOR
    )

    layer_coordinators = tuple(
        agent for agent in AGENTS
        if agent.agent_type == AgentType.LAYER_COORDINATOR
    )

    specialists = tuple(
        agent for agent in AGENTS
        if agent.agent_type == AgentType.SPECIALIST
    )

    if len(global_agents) != 1:
        raise ValueError("Exactly one global coordinator is required.")

    if len(layer_coordinators) != 10:
        raise ValueError("Exactly ten layer coordinators are required.")

    if len(specialists) != 200:
        raise ValueError("Exactly 200 specialists are required.")

    global_id = global_agents[0].agent_id

    for layer in LAYERS:
        layer_agents = get_agents_for_layer(layer.layer_id)

        coordinators = tuple(
            agent for agent in layer_agents
            if agent.agent_type == AgentType.LAYER_COORDINATOR
        )

        layer_specialists = tuple(
            agent for agent in layer_agents
            if agent.agent_type == AgentType.SPECIALIST
        )

        if len(coordinators) != 1:
            raise ValueError(
                f"Layer {layer.layer_id} must have one coordinator."
            )

        if len(layer_specialists) != SPECIALISTS_PER_LAYER:
            raise ValueError(
                f"Layer {layer.layer_id} must have 20 specialists."
            )

        coordinator = coordinators[0]

        if coordinator.coordinator_id != global_id:
            raise ValueError("Layer coordinator hierarchy is invalid.")

        for specialist in layer_specialists:
            if specialist.coordinator_id != coordinator.agent_id:
                raise ValueError("Specialist coordinator mapping is invalid.")

    for agent in AGENTS:
        if agent.contract_version != AGENT_CONTRACT_VERSION:
            raise ValueError("Agent contract version mismatch.")

        if agent.status != "registered":
            raise ValueError("Unexpected initial agent status.")

        if agent.permission_profile != "advisory_only":
            raise ValueError("Initial agents must remain advisory-only.")

        if agent.capabilities != ADVISORY_CAPABILITIES:
            raise ValueError("Unexpected agent capability assignment.")

        if "execute" in agent.capabilities:
            raise ValueError("Execution capability is prohibited.")

        if not agent.memory_namespace:
            raise ValueError("Every agent requires a memory namespace.")

        if agent.agent_type != AgentType.GLOBAL_COORDINATOR:
            if not agent.layer_id or not agent.layer_name:
                raise ValueError("Layer assignment is required.")

    return True


validate_agent_registry()
