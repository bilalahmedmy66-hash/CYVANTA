from fastapi import APIRouter, Depends

from app.agents.identity import (
    AGENT_CONTRACT_VERSION,
    AGENTS,
    ADVISORY_CAPABILITIES,
    AgentType,
)
from app.fortress.registry import LAYERS
from app.models import Membership
from app.security.dependencies import get_current_membership


router = APIRouter(
    prefix="/agent-intelligence",
    tags=["Agent Intelligence"],
)


def _serialize_agent(agent):
    return {
        "agent_id": agent.agent_id,
        "agent_type": agent.agent_type.value,
        "layer_id": agent.layer_id,
        "layer_name": agent.layer_name,
        "role": agent.role,
        "responsibility": agent.responsibility,
        "contract_version": agent.contract_version,
        "capabilities": list(agent.capabilities),
        "permission_profile": agent.permission_profile,
        "memory_namespace": agent.memory_namespace,
        "coordinator_id": agent.coordinator_id,
        "status": agent.status,
    }


@router.get("/registry")
def get_agent_registry(
    membership: Membership = Depends(get_current_membership),
):
    """Return authenticated, read-only metadata for the global V2 agent registry."""

    global_coordinator = next(
        agent for agent in AGENTS
        if agent.agent_type == AgentType.GLOBAL_COORDINATOR
    )

    layer_coordinators = {
        agent.layer_id: agent
        for agent in AGENTS
        if agent.agent_type == AgentType.LAYER_COORDINATOR
    }

    layer_summaries = [
        {
            "layer_id": layer.layer_id,
            "layer_name": layer.name,
            "coordinator_id": layer_coordinators[layer.layer_id].agent_id,
            "specialist_count": sum(
                agent.agent_type == AgentType.SPECIALIST
                and agent.layer_id == layer.layer_id
                for agent in AGENTS
            ),
        }
        for layer in LAYERS
    ]

    return {
        "organization_id": membership.organization_id,
        "registry_scope": "global_static_registry",
        "contract_version": AGENT_CONTRACT_VERSION,
        "execution_model": "logical_identities_not_persistent_workers",
        "metadata_only": True,
        "safety_boundary": {
            "permission_profile": "advisory_only",
            "capabilities": list(ADVISORY_CAPABILITIES),
            "security_actions_enabled": False,
            "agent_execution_enabled": False,
        },
        "summary": {
            "registered_identities": len(AGENTS),
            "global_coordinators": 1,
            "layer_coordinators": len(layer_coordinators),
            "specialists": sum(
                agent.agent_type == AgentType.SPECIALIST
                for agent in AGENTS
            ),
            "layers": len(LAYERS),
            "running_workers": None,
        },
        "global_coordinator": _serialize_agent(global_coordinator),
        "layers": layer_summaries,
        "agents": [_serialize_agent(agent) for agent in AGENTS],
    }