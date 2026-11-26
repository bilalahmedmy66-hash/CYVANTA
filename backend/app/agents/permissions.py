"""Deterministic, advisory-only permission checks for CYVANTA FORTRESS V2."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from app.agents.identity import AGENTS, get_agent


PERMISSION_CONTRACT_VERSION = "2.0.0"


class AgentPermission(str, Enum):
    READ_AGENT_METADATA = "read_agent_metadata"
    READ_APPROVED_SIMULATION_RESULTS = "read_approved_simulation_results"
    SUBMIT_ADVISORY_PROPOSAL = "submit_advisory_proposal"


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    agent_id: str
    permission: str
    reason: str
    required_capabilities: tuple[str, ...] = ()
    contract_version: str = PERMISSION_CONTRACT_VERSION


# Capabilities describe what an agent is designed to do. They do not,
# by themselves, grant permission.
PERMISSION_REQUIREMENTS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    AgentPermission.READ_AGENT_METADATA.value: ("observe",),
    AgentPermission.READ_APPROVED_SIMULATION_RESULTS.value: ("observe", "analyze"),
    AgentPermission.SUBMIT_ADVISORY_PROPOSAL.value: ("propose",),
})

# Explicitly documented as non-grantable by this advisory permission layer.
FORBIDDEN_PERMISSION_NAMES = frozenset({
    "read_assets",
    "access_assets",
    "approve_actions",
    "approve_requests",
    "activate_workers",
    "dispatch_work",
    "execute_actions",
    "execute_commands",
    "modify_policies",
    "control_emergency_stop",
    "disable_emergency_stop",
    "perform_containment",
    "perform_remediation",
})


def _deny(agent_id: str, permission: str, reason: str) -> PermissionDecision:
    return PermissionDecision(
        allowed=False,
        agent_id=agent_id,
        permission=permission,
        reason=reason,
    )


def evaluate_permission(
    agent_id: str,
    permission: str | AgentPermission,
    *,
    organization_id: str | None = None,
    tenant_id: str | None = None,
    resource_organization_id: str | None = None,
    resource_tenant_id: str | None = None,
    resource_is_approved: bool | None = None,
) -> PermissionDecision:
    """Evaluate one advisory permission without I/O or side effects.

    Organization and tenant scope must match for simulation-result reads
    and advisory proposals. Reading simulation results additionally requires
    an independently verified approval flag supplied by the caller.

    This function does not authenticate the caller, verify approval records,
    retrieve data, or execute proposals. Those responsibilities remain outside
    this permission contract.
    """
    normalized_agent_id = agent_id if isinstance(agent_id, str) else ""

    if not normalized_agent_id.strip():
        return _deny("", str(permission), "Invalid or missing agent ID.")

    if isinstance(permission, AgentPermission):
        permission_name = permission.value
    elif isinstance(permission, str):
        permission_name = permission
    else:
        return _deny(normalized_agent_id, "", "Invalid permission value.")

    if permission_name in FORBIDDEN_PERMISSION_NAMES:
        return _deny(
            normalized_agent_id,
            permission_name,
            "This operation is forbidden for advisory agents.",
        )

    required = PERMISSION_REQUIREMENTS.get(permission_name)
    if required is None:
        return _deny(
            normalized_agent_id,
            permission_name,
            "Unknown permission; access denied by default.",
        )

    try:
        agent = get_agent(normalized_agent_id)
    except (KeyError, ValueError, TypeError):
        return _deny(
            normalized_agent_id,
            permission_name,
            "Unknown agent; access denied.",
        )

    if agent.permission_profile != "advisory_only":
        return _deny(
            normalized_agent_id,
            permission_name,
            "Agent does not have the required advisory-only profile.",
        )

    if agent.status != "registered":
        return _deny(
            normalized_agent_id,
            permission_name,
            "Agent is not in registered status.",
        )

    agent_capabilities = frozenset(agent.capabilities)
    if not all(capability in agent_capabilities for capability in required):
        return _deny(
            normalized_agent_id,
            permission_name,
            "Agent is missing a capability required by this permission.",
        )

    if permission_name != AgentPermission.READ_AGENT_METADATA.value:
        scope_values = (
            organization_id,
            tenant_id,
            resource_organization_id,
            resource_tenant_id,
        )
        if any(
            not isinstance(value, str) or not value.strip()
            for value in scope_values
        ):
            return _deny(
                normalized_agent_id,
                permission_name,
                "Organization and tenant scope are required.",
            )

        if organization_id != resource_organization_id:
            return _deny(
                normalized_agent_id,
                permission_name,
                "Organization scope mismatch; access denied.",
            )

        if tenant_id != resource_tenant_id:
            return _deny(
                normalized_agent_id,
                permission_name,
                "Tenant scope mismatch; access denied.",
            )

    if (
        permission_name
        == AgentPermission.READ_APPROVED_SIMULATION_RESULTS.value
        and resource_is_approved is not True
    ):
        return _deny(
            normalized_agent_id,
            permission_name,
            "Simulation result approval was not affirmatively verified.",
        )

    return PermissionDecision(
        allowed=True,
        agent_id=normalized_agent_id,
        permission=permission_name,
        reason="Permission granted within the advisory-only scope.",
        required_capabilities=required,
    )


def validate_permission_contract() -> bool:
    """Validate static permission definitions against the V2 agent registry."""
    if len(AGENTS) != 211:
        return False

    if len(PERMISSION_REQUIREMENTS) != 3:
        return False

    if set(PERMISSION_REQUIREMENTS) != {
        permission.value for permission in AgentPermission
    }:
        return False

    for agent in AGENTS:
        if agent.permission_profile != "advisory_only":
            return False
        if not {"observe", "analyze", "propose"}.issubset(
            frozenset(agent.capabilities)
        ):
            return False

    return True
