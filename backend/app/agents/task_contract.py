"""Deterministic, bounded advisory task delegation for CYVANTA FORTRESS V2."""

from dataclasses import dataclass
from enum import Enum

from app.agents.identity import get_agent
from app.agents.permissions import AgentPermission, evaluate_permission


TASK_CONTRACT_VERSION = "2.0.0"
MAX_DELEGATION_DEPTH = 2


class AdvisoryTaskType(str, Enum):
    ANALYZE = "analyze"
    REVIEW_EVIDENCE = "review_evidence"
    IDENTIFY_PATTERNS = "identify_patterns"
    SUMMARIZE_FINDINGS = "summarize_findings"
    PREPARE_RECOMMENDATION = "prepare_recommendation"


TASK_CAPABILITIES = {
    AdvisoryTaskType.ANALYZE.value: ("analyze",),
    AdvisoryTaskType.REVIEW_EVIDENCE.value: ("observe", "analyze"),
    AdvisoryTaskType.IDENTIFY_PATTERNS.value: ("analyze",),
    AdvisoryTaskType.SUMMARIZE_FINDINGS.value: ("analyze",),
    AdvisoryTaskType.PREPARE_RECOMMENDATION.value: ("analyze", "propose"),
}


@dataclass(frozen=True, slots=True)
class TaskProposal:
    task_id: str
    assigned_by: str
    assigned_to: str
    task_type: str
    objective: str
    organization_id: str
    tenant_id: str
    parent_task: "TaskContract | None" = None


@dataclass(frozen=True, slots=True)
class TaskContract:
    task_id: str
    contract_version: str
    parent_task_id: str | None
    assigned_by: str
    assigned_to: str
    layer_id: str
    task_type: str
    objective: str
    organization_id: str
    tenant_id: str
    required_capabilities: tuple[str, ...]
    delegation_depth: int
    delegation_path: tuple[str, ...]
    status: str = "proposed"


@dataclass(frozen=True, slots=True)
class TaskValidationResult:
    allowed: bool
    reason: str
    task: TaskContract | None = None
    contract_version: str = TASK_CONTRACT_VERSION


def _valid_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _deny(reason: str) -> TaskValidationResult:
    return TaskValidationResult(allowed=False, reason=reason)


def _validate_parent(parent: TaskContract) -> bool:
    """Validate the structural integrity of an existing parent contract."""
    if not isinstance(parent, TaskContract):
        return False

    if parent.contract_version != TASK_CONTRACT_VERSION:
        return False

    if parent.status != "proposed":
        return False

    if not 1 <= parent.delegation_depth <= MAX_DELEGATION_DEPTH:
        return False

    if len(parent.delegation_path) != parent.delegation_depth + 1:
        return False

    if len(set(parent.delegation_path)) != len(parent.delegation_path):
        return False

    if parent.delegation_path[-1] != parent.assigned_to:
        return False

    if parent.delegation_path[-2] != parent.assigned_by:
        return False

    try:
        delegator = get_agent(parent.assigned_by)
        receiver = get_agent(parent.assigned_to)
    except (KeyError, ValueError, TypeError):
        return False

    if delegator.permission_profile != "advisory_only":
        return False

    if receiver.permission_profile != "advisory_only":
        return False

    if parent.delegation_depth == 1:
        return (
            delegator.agent_type.value == "global_coordinator"
            and receiver.agent_type.value == "layer_coordinator"
            and receiver.layer_id == parent.layer_id
        )

    if parent.delegation_depth == 2:
        return (
            delegator.agent_type.value == "layer_coordinator"
            and receiver.agent_type.value == "specialist"
            and delegator.layer_id == receiver.layer_id == parent.layer_id
        )

    return False


def validate_task_delegation(proposal: TaskProposal) -> TaskValidationResult:
    """Validate a proposed delegation without executing or scheduling a task."""
    if not isinstance(proposal, TaskProposal):
        return _deny("Invalid task proposal object.")

    text_fields = (
        proposal.task_id,
        proposal.assigned_by,
        proposal.assigned_to,
        proposal.task_type,
        proposal.objective,
        proposal.organization_id,
        proposal.tenant_id,
    )
    if not all(_valid_text(value) for value in text_fields):
        return _deny("Missing or invalid required task fields.")

    if proposal.assigned_by == proposal.assigned_to:
        return _deny("Self-delegation is forbidden.")

    try:
        task_type = AdvisoryTaskType(proposal.task_type)
    except (ValueError, TypeError):
        return _deny("Unsupported task type.")

    required_capabilities = TASK_CAPABILITIES[task_type.value]

    try:
        delegator = get_agent(proposal.assigned_by)
        receiver = get_agent(proposal.assigned_to)
    except (KeyError, ValueError, TypeError):
        return _deny("Unknown delegating or receiving agent.")

    if delegator.permission_profile != "advisory_only":
        return _deny("Delegating agent is not advisory-only.")

    if receiver.permission_profile != "advisory_only":
        return _deny("Receiving agent is not advisory-only.")

    if delegator.status != "registered" or receiver.status != "registered":
        return _deny("Both agents must be registered.")

    if not all(
        capability in receiver.capabilities
        for capability in required_capabilities
    ):
        return _deny("Receiving agent lacks required task capabilities.")

    permission = evaluate_permission(
        delegator.agent_id,
        AgentPermission.SUBMIT_ADVISORY_PROPOSAL,
        organization_id=proposal.organization_id,
        tenant_id=proposal.tenant_id,
        resource_organization_id=proposal.organization_id,
        resource_tenant_id=proposal.tenant_id,
    )
    if not permission.allowed:
        return _deny("Delegating agent lacks advisory proposal permission.")

    parent = proposal.parent_task

    if delegator.agent_type.value == "global_coordinator":
        if parent is not None:
            return _deny("Global coordinator tasks cannot have a parent task.")

        if receiver.agent_type.value != "layer_coordinator":
            return _deny(
                "Global coordinator may delegate only to layer coordinators."
            )

        if receiver.layer_id is None:
            return _deny("Receiving layer coordinator has no valid layer.")

        depth = 1
        parent_task_id = None
        path = (delegator.agent_id, receiver.agent_id)
        layer_id = receiver.layer_id

    elif delegator.agent_type.value == "layer_coordinator":
        if receiver.agent_type.value != "specialist":
            return _deny(
                "Layer coordinator may delegate only to its own specialists."
            )

        if delegator.layer_id != receiver.layer_id:
            return _deny("Cross-layer delegation is forbidden.")

        if parent is None or not _validate_parent(parent):
            return _deny("A valid parent task is required for specialist delegation.")

        if parent.assigned_to != delegator.agent_id:
            return _deny("Parent task was not assigned to this layer coordinator.")

        if parent.layer_id != delegator.layer_id:
            return _deny("Parent task layer does not match the delegating layer.")

        if (
            parent.organization_id != proposal.organization_id
            or parent.tenant_id != proposal.tenant_id
        ):
            return _deny("Parent task organization or tenant scope mismatch.")

        if parent.delegation_depth >= MAX_DELEGATION_DEPTH:
            return _deny("Maximum delegation depth exceeded.")

        depth = parent.delegation_depth + 1
        parent_task_id = parent.task_id
        path = parent.delegation_path + (receiver.agent_id,)
        layer_id = delegator.layer_id

    else:
        return _deny("Specialists and other agents cannot delegate tasks.")

    if depth > MAX_DELEGATION_DEPTH:
        return _deny("Maximum delegation depth exceeded.")

    if len(set(path)) != len(path):
        return _deny("Circular delegation path detected.")

    if receiver.agent_id in path[:-1]:
        return _deny("Circular delegation is forbidden.")

    task = TaskContract(
        task_id=proposal.task_id.strip(),
        contract_version=TASK_CONTRACT_VERSION,
        parent_task_id=parent_task_id,
        assigned_by=delegator.agent_id,
        assigned_to=receiver.agent_id,
        layer_id=layer_id,
        task_type=task_type.value,
        objective=proposal.objective.strip(),
        organization_id=proposal.organization_id.strip(),
        tenant_id=proposal.tenant_id.strip(),
        required_capabilities=required_capabilities,
        delegation_depth=depth,
        delegation_path=path,
    )

    return TaskValidationResult(
        allowed=True,
        reason="Advisory task delegation contract validated.",
        task=task,
    )


def validate_task_contract() -> bool:
    """Validate the static V2 delegation contract."""
    return (
        TASK_CONTRACT_VERSION == "2.0.0"
        and MAX_DELEGATION_DEPTH == 2
        and len(TASK_CAPABILITIES) == len(AdvisoryTaskType)
        and all(
            isinstance(task_type, str)
            and isinstance(capabilities, tuple)
            and bool(capabilities)
            and all(
                capability in {"observe", "analyze", "propose"}
                for capability in capabilities
            )
            for task_type, capabilities in TASK_CAPABILITIES.items()
        )
    )
