"""Control-scoped advisory task binding for CYVANTA FORTRESS V2."""

from dataclasses import dataclass

from app.agents.control_mapping import (
    CONTROL_MAPPING_VERSION,
    ControlAgentMapping,
    get_control_agent_mapping,
)
from app.agents.task_contract import (
    TASK_CONTRACT_VERSION,
    TaskContract,
    TaskProposal,
    validate_task_delegation,
)

CONTROL_TASK_ADAPTER_VERSION = "2.0.0"


@dataclass(frozen=True, slots=True)
class ControlTaskProposal:
    """A task proposal explicitly scoped to one registered V1 control."""

    control_id: str
    task_id: str
    assigned_by: str
    assigned_to: str
    task_type: str
    objective: str
    organization_id: str
    tenant_id: str
    parent_binding: "ControlTaskBinding | None" = None


@dataclass(frozen=True, slots=True)
class ControlTaskBinding:
    """Immutable association between a V1 control and a validated V2 task."""

    control_mapping: ControlAgentMapping
    task: TaskContract
    adapter_version: str = CONTROL_TASK_ADAPTER_VERSION


@dataclass(frozen=True, slots=True)
class ControlTaskValidationResult:
    allowed: bool
    reason: str
    binding: ControlTaskBinding | None = None
    adapter_version: str = CONTROL_TASK_ADAPTER_VERSION


def _deny(reason: str) -> ControlTaskValidationResult:
    return ControlTaskValidationResult(
        allowed=False,
        reason=reason,
    )


def validate_control_task(
    proposal: ControlTaskProposal,
) -> ControlTaskValidationResult:
    """Validate and bind an advisory task to exactly one registered control.

    This function does not schedule, execute, persist, or dispatch tasks.
    """
    if not isinstance(proposal, ControlTaskProposal):
        return _deny("Invalid control task proposal object.")

    try:
        mapping = get_control_agent_mapping(proposal.control_id)
    except (KeyError, TypeError):
        return _deny("Unknown or invalid control identifier.")

    parent_binding = proposal.parent_binding

    if parent_binding is not None:
        if not isinstance(parent_binding, ControlTaskBinding):
            return _deny("Invalid parent control binding.")

        if parent_binding.adapter_version != CONTROL_TASK_ADAPTER_VERSION:
            return _deny("Parent control binding version mismatch.")

        if parent_binding.control_mapping != mapping:
            return _deny("Parent task belongs to a different control mapping.")

        if not isinstance(parent_binding.task, TaskContract):
            return _deny("Parent binding contains an invalid task contract.")

        if parent_binding.task.contract_version != TASK_CONTRACT_VERSION:
            return _deny("Parent task contract version mismatch.")

        if (
            parent_binding.task.organization_id != proposal.organization_id
            or parent_binding.task.tenant_id != proposal.tenant_id
        ):
            return _deny("Parent task organization or tenant scope mismatch.")

        if parent_binding.task.layer_id != mapping.layer_id:
            return _deny("Parent task layer does not match the control.")

    if proposal.assigned_to == mapping.coordinator_id:
        if proposal.parent_binding is not None:
            return _deny("Layer coordinator tasks cannot have a parent binding.")

        if proposal.assigned_by == mapping.coordinator_id:
            return _deny("Self-delegation is forbidden.")

    elif proposal.assigned_to in mapping.eligible_specialist_ids:
        if proposal.assigned_by != mapping.coordinator_id:
            return _deny(
                "Specialist tasks must be delegated by the mapped layer coordinator."
            )

        if parent_binding is None:
            return _deny(
                "Specialist tasks require a parent binding for the same control."
            )

    else:
        return _deny(
            "Receiving agent is not eligible for the selected control."
        )

    task_proposal = TaskProposal(
        task_id=proposal.task_id,
        assigned_by=proposal.assigned_by,
        assigned_to=proposal.assigned_to,
        task_type=proposal.task_type,
        objective=proposal.objective,
        organization_id=proposal.organization_id,
        tenant_id=proposal.tenant_id,
        parent_task=(
            parent_binding.task if parent_binding is not None else None
        ),
    )

    validation = validate_task_delegation(task_proposal)

    if not validation.allowed or validation.task is None:
        return _deny(validation.reason)

    if validation.task.layer_id != mapping.layer_id:
        return _deny("Validated task layer does not match the selected control.")

    binding = ControlTaskBinding(
        control_mapping=mapping,
        task=validation.task,
    )

    return ControlTaskValidationResult(
        allowed=True,
        reason="Control-scoped advisory task binding validated.",
        binding=binding,
    )


def validate_control_task_adapter() -> bool:
    """Validate static adapter version compatibility."""
    return (
        CONTROL_TASK_ADAPTER_VERSION == "2.0.0"
        and CONTROL_MAPPING_VERSION == "2.0.0"
        and TASK_CONTRACT_VERSION == "2.0.0"
        and callable(validate_control_task)
    )
