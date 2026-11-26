"""Tests for control-scoped advisory task binding."""

from dataclasses import FrozenInstanceError, replace

import pytest

from app.agents.control_mapping import get_control_agent_mapping
from app.agents.control_task_adapter import (
    CONTROL_TASK_ADAPTER_VERSION,
    ControlTaskBinding,
    ControlTaskProposal,
    validate_control_task,
    validate_control_task_adapter,
)
from app.agents.identity import get_agent


ORG = "org-test"
TENANT = "tenant-test"
GLOBAL_COORDINATOR = "CYV-GLOBAL-COORD-001"
CONTROL_ID = "IAM-001"


def _coordinator_proposal(control_id=CONTROL_ID, **overrides):
    mapping = get_control_agent_mapping(control_id)
    values = {
        "control_id": control_id,
        "task_id": "task-coordinator-001",
        "assigned_by": GLOBAL_COORDINATOR,
        "assigned_to": mapping.coordinator_id,
        "task_type": "analyze",
        "objective": "Review the selected control evidence.",
        "organization_id": ORG,
        "tenant_id": TENANT,
    }
    values.update(overrides)
    return ControlTaskProposal(**values)


def _valid_parent_binding(control_id=CONTROL_ID):
    result = validate_control_task(_coordinator_proposal(control_id))
    assert result.allowed
    assert result.binding is not None
    return result.binding


def _specialist_proposal(control_id=CONTROL_ID, **overrides):
    mapping = get_control_agent_mapping(control_id)
    parent = _valid_parent_binding(control_id)
    values = {
        "control_id": control_id,
        "task_id": "task-specialist-001",
        "assigned_by": mapping.coordinator_id,
        "assigned_to": mapping.eligible_specialist_ids[0],
        "task_type": "analyze",
        "objective": "Analyze evidence for the selected control.",
        "organization_id": ORG,
        "tenant_id": TENANT,
        "parent_binding": parent,
    }
    values.update(overrides)
    return ControlTaskProposal(**values)


def test_valid_coordinator_task_is_bound_to_control():
    result = validate_control_task(_coordinator_proposal())

    assert result.allowed
    assert result.binding is not None
    assert result.binding.control_mapping.control_id == CONTROL_ID
    assert result.binding.task.layer_id == "identity_authentication"
    assert result.binding.task.delegation_depth == 1


def test_valid_specialist_task_uses_same_control_parent():
    result = validate_control_task(_specialist_proposal())

    assert result.allowed
    assert result.binding is not None
    assert result.binding.control_mapping.control_id == CONTROL_ID
    assert result.binding.task.delegation_depth == 2
    assert result.binding.task.parent_task_id == "task-coordinator-001"


def test_unknown_control_is_rejected():
    proposal = ControlTaskProposal(
        control_id="UNKNOWN-001",
        task_id="task-unknown-control-001",
        assigned_by=GLOBAL_COORDINATOR,
        assigned_to="CYV-L01-COORD-001",
        task_type="analyze",
        objective="Test rejection of an unknown control.",
        organization_id=ORG,
        tenant_id=TENANT,
    )

    result = validate_control_task(proposal)

    assert not result.allowed
    assert result.binding is None
    assert result.reason == "Unknown or invalid control identifier."


def test_invalid_proposal_object_is_rejected():
    result = validate_control_task(None)

    assert not result.allowed


def test_unmapped_receiving_agent_is_rejected():
    result = validate_control_task(
        _coordinator_proposal(assigned_to=GLOBAL_COORDINATOR)
    )

    assert not result.allowed


def test_specialist_cannot_receive_direct_global_delegation():
    mapping = get_control_agent_mapping(CONTROL_ID)
    result = validate_control_task(
        _coordinator_proposal(
            assigned_to=mapping.eligible_specialist_ids[0]
        )
    )

    assert not result.allowed


def test_specialist_requires_parent_binding():
    proposal = _specialist_proposal(parent_binding=None)

    result = validate_control_task(proposal)

    assert not result.allowed


def test_specialist_must_be_delegated_by_its_layer_coordinator():
    result = validate_control_task(
        _specialist_proposal(assigned_by=GLOBAL_COORDINATOR)
    )

    assert not result.allowed


def test_parent_binding_from_another_control_is_rejected():
    other_control = "IAM-002"
    other_parent = _valid_parent_binding(other_control)

    result = validate_control_task(
        _specialist_proposal(parent_binding=other_parent)
    )

    assert not result.allowed
    assert "different control" in result.reason


def test_parent_binding_with_different_tenant_is_rejected():
    parent = _valid_parent_binding()
    result = validate_control_task(
        _specialist_proposal(tenant_id="another-tenant")
    )

    assert not result.allowed
    assert "scope mismatch" in result.reason


def test_parent_binding_with_different_organization_is_rejected():
    result = validate_control_task(
        _specialist_proposal(organization_id="another-org")
    )

    assert not result.allowed
    assert "scope mismatch" in result.reason


def test_invalid_task_type_is_rejected():
    result = validate_control_task(
        _coordinator_proposal(task_type="execute")
    )

    assert not result.allowed


def test_empty_objective_is_rejected():
    result = validate_control_task(
        _coordinator_proposal(objective=" ")
    )

    assert not result.allowed


def test_parent_binding_version_mismatch_is_rejected():
    parent = _valid_parent_binding()
    invalid_parent = replace(parent, adapter_version="99.0.0")

    result = validate_control_task(
        _specialist_proposal(parent_binding=invalid_parent)
    )

    assert not result.allowed


def test_binding_is_immutable():
    binding = _valid_parent_binding()

    with pytest.raises(FrozenInstanceError):
        binding.adapter_version = "99.0.0"


def test_control_mapping_is_preserved():
    result = validate_control_task(_coordinator_proposal())

    assert result.binding is not None
    assert result.binding.control_mapping == get_control_agent_mapping(CONTROL_ID)
    assert result.binding.control_mapping.vault_id == "identity"


def test_task_receiver_is_registered():
    mapping = get_control_agent_mapping(CONTROL_ID)

    assert get_agent(mapping.coordinator_id).status == "registered"


def test_adapter_contract_validation():
    assert CONTROL_TASK_ADAPTER_VERSION == "2.0.0"
    assert validate_control_task_adapter()
