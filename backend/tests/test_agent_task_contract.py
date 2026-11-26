import pytest

from app.agents.identity import AGENTS, AgentType
from app.agents.task_contract import (
    MAX_DELEGATION_DEPTH,
    TASK_CAPABILITIES,
    TASK_CONTRACT_VERSION,
    AdvisoryTaskType,
    TaskContract,
    TaskProposal,
    validate_task_contract,
    validate_task_delegation,
)


GLOBAL = next(agent for agent in AGENTS if agent.agent_type == AgentType.GLOBAL_COORDINATOR)
LAYERS = [
    agent for agent in AGENTS
    if agent.agent_type == AgentType.LAYER_COORDINATOR
]
SPECIALISTS = [
    agent for agent in AGENTS
    if agent.agent_type == AgentType.SPECIALIST
]

ORG = "org-task-test"
TENANT = "tenant-task-test"


def proposal(delegator, receiver, **overrides):
    values = {
        "task_id": "task-001",
        "assigned_by": delegator.agent_id,
        "assigned_to": receiver.agent_id,
        "task_type": AdvisoryTaskType.ANALYZE.value,
        "objective": "Analyze supplied synthetic evidence",
        "organization_id": ORG,
        "tenant_id": TENANT,
    }
    values.update(overrides)
    return TaskProposal(**values)


def make_layer_task(layer=None):
    layer = layer or LAYERS[0]
    result = validate_task_delegation(
        proposal(GLOBAL, layer, task_id="parent-001")
    )
    assert result.allowed is True
    return result.task


def test_static_contract_is_valid():
    assert validate_task_contract() is True
    assert TASK_CONTRACT_VERSION == "2.0.0"
    assert MAX_DELEGATION_DEPTH == 2


def test_exactly_ten_layer_coordinators_and_two_hundred_specialists():
    assert len(LAYERS) == 10
    assert len(SPECIALISTS) == 200


def test_global_coordinator_can_delegate_to_layer_coordinator():
    result = validate_task_delegation(proposal(GLOBAL, LAYERS[0]))

    assert result.allowed is True
    assert result.task is not None
    assert result.task.delegation_depth == 1
    assert result.task.parent_task_id is None
    assert result.task.layer_id == LAYERS[0].layer_id


def test_layer_coordinator_can_delegate_to_own_specialist():
    layer = LAYERS[0]
    specialist = next(
        agent for agent in SPECIALISTS if agent.layer_id == layer.layer_id
    )
    parent = make_layer_task(layer)

    result = validate_task_delegation(
        proposal(layer, specialist, parent_task=parent)
    )

    assert result.allowed is True
    assert result.task.delegation_depth == 2
    assert result.task.parent_task_id == parent.task_id
    assert result.task.delegation_path == (
        GLOBAL.agent_id,
        layer.agent_id,
        specialist.agent_id,
    )


def test_all_layer_coordinators_can_receive_global_tasks():
    for layer in LAYERS:
        result = validate_task_delegation(proposal(GLOBAL, layer))
        assert result.allowed is True
        assert result.task.layer_id == layer.layer_id


def test_all_specialists_can_receive_tasks_from_their_own_coordinator():
    for specialist in SPECIALISTS:
        layer = next(
            item for item in LAYERS if item.layer_id == specialist.layer_id
        )
        parent = make_layer_task(layer)
        result = validate_task_delegation(
            proposal(layer, specialist, parent_task=parent)
        )
        assert result.allowed is True


def test_global_cannot_delegate_directly_to_specialist():
    result = validate_task_delegation(proposal(GLOBAL, SPECIALISTS[0]))
    assert result.allowed is False


def test_layer_coordinator_cannot_delegate_without_parent():
    result = validate_task_delegation(
        proposal(LAYERS[0], SPECIALISTS[0])
    )
    assert result.allowed is False


def test_cross_layer_delegation_is_rejected():
    source_layer = LAYERS[0]
    target_specialist = next(
        agent for agent in SPECIALISTS
        if agent.layer_id == LAYERS[1].layer_id
    )
    parent = make_layer_task(source_layer)

    result = validate_task_delegation(
        proposal(source_layer, target_specialist, parent_task=parent)
    )
    assert result.allowed is False


def test_layer_coordinator_cannot_delegate_to_another_layer_coordinator():
    result = validate_task_delegation(
        proposal(LAYERS[0], LAYERS[1], parent_task=make_layer_task())
    )
    assert result.allowed is False


def test_specialist_cannot_delegate():
    specialist = SPECIALISTS[0]
    layer = next(item for item in LAYERS if item.layer_id == specialist.layer_id)

    result = validate_task_delegation(
        proposal(specialist, layer, parent_task=make_layer_task(layer))
    )
    assert result.allowed is False


def test_specialist_cannot_delegate_to_another_specialist():
    layer = LAYERS[0]
    same_layer = [
        item for item in SPECIALISTS if item.layer_id == layer.layer_id
    ]
    parent = make_layer_task(layer)

    result = validate_task_delegation(
        proposal(same_layer[0], same_layer[1], parent_task=parent)
    )
    assert result.allowed is False


def test_self_delegation_is_rejected():
    result = validate_task_delegation(proposal(GLOBAL, GLOBAL))
    assert result.allowed is False


@pytest.mark.parametrize(
    "task_type",
    [item.value for item in AdvisoryTaskType],
)
def test_every_supported_task_type_is_accepted_for_layer_task(task_type):
    result = validate_task_delegation(
        proposal(GLOBAL, LAYERS[0], task_type=task_type)
    )
    assert result.allowed is True
    assert result.task.required_capabilities == TASK_CAPABILITIES[task_type]


@pytest.mark.parametrize(
    "task_type",
    ["execute", "scan_asset", "containment", "remediate", "approve", ""],
)
def test_unsupported_task_types_are_rejected(task_type):
    result = validate_task_delegation(
        proposal(GLOBAL, LAYERS[0], task_type=task_type)
    )
    assert result.allowed is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", ""),
        ("assigned_by", ""),
        ("assigned_to", ""),
        ("objective", ""),
        ("organization_id", ""),
        ("tenant_id", ""),
        ("objective", "   "),
    ],
)
def test_missing_required_fields_are_rejected(field, value):
    result = validate_task_delegation(
        proposal(GLOBAL, LAYERS[0], **{field: value})
    )
    assert result.allowed is False


def test_unknown_delegator_is_rejected():
    result = validate_task_delegation(
        proposal(GLOBAL, LAYERS[0], assigned_by="UNKNOWN-AGENT")
    )
    assert result.allowed is False


def test_unknown_receiver_is_rejected():
    result = validate_task_delegation(
        proposal(GLOBAL, LAYERS[0], assigned_to="UNKNOWN-AGENT")
    )
    assert result.allowed is False


def test_parent_task_must_be_a_valid_contract():
    result = validate_task_delegation(
        proposal(LAYERS[0], SPECIALISTS[0], parent_task="not-a-task")
    )
    assert result.allowed is False


def test_parent_task_must_be_assigned_to_delegating_coordinator():
    parent = make_layer_task(LAYERS[1])
    result = validate_task_delegation(
        proposal(LAYERS[0], SPECIALISTS[0], parent_task=parent)
    )
    assert result.allowed is False


def test_parent_task_scope_must_match_child_scope():
    parent = make_layer_task()
    result = validate_task_delegation(
        proposal(
            LAYERS[0],
            SPECIALISTS[0],
            parent_task=parent,
            organization_id="another-org",
        )
    )
    assert result.allowed is False


def test_parent_task_tenant_must_match_child_scope():
    parent = make_layer_task()
    result = validate_task_delegation(
        proposal(
            LAYERS[0],
            SPECIALISTS[0],
            parent_task=parent,
            tenant_id="another-tenant",
        )
    )
    assert result.allowed is False


def test_parent_task_at_maximum_depth_cannot_be_delegated_further():
    parent = make_layer_task()
    specialist = SPECIALISTS[0]

    depth_two_parent = TaskContract(
        task_id="depth-two",
        contract_version=TASK_CONTRACT_VERSION,
        parent_task_id=parent.task_id,
        assigned_by=LAYERS[0].agent_id,
        assigned_to=specialist.agent_id,
        layer_id=LAYERS[0].layer_id,
        task_type="analyze",
        objective="Synthetic child task",
        organization_id=ORG,
        tenant_id=TENANT,
        required_capabilities=("analyze",),
        delegation_depth=2,
        delegation_path=(
            GLOBAL.agent_id,
            LAYERS[0].agent_id,
            specialist.agent_id,
        ),
    )

    result = validate_task_delegation(
        proposal(specialist, LAYERS[0], parent_task=depth_two_parent)
    )
    assert result.allowed is False


def test_parent_with_wrong_contract_version_is_rejected():
    parent = make_layer_task()
    invalid_parent = TaskContract(
        **{
            **{
                field: getattr(parent, field)
                for field in parent.__dataclass_fields__
            },
            "contract_version": "9.9.9",
        }
    )

    result = validate_task_delegation(
        proposal(LAYERS[0], SPECIALISTS[0], parent_task=invalid_parent)
    )
    assert result.allowed is False


def test_parent_with_duplicate_delegation_path_is_rejected():
    parent = make_layer_task()
    invalid_parent = TaskContract(
        **{
            **{
                field: getattr(parent, field)
                for field in parent.__dataclass_fields__
            },
            "delegation_path": (
                GLOBAL.agent_id,
                GLOBAL.agent_id,
            ),
        }
    )

    result = validate_task_delegation(
        proposal(LAYERS[0], SPECIALISTS[0], parent_task=invalid_parent)
    )
    assert result.allowed is False


def test_parent_with_wrong_status_is_rejected():
    parent = make_layer_task()
    invalid_parent = TaskContract(
        **{
            **{
                field: getattr(parent, field)
                for field in parent.__dataclass_fields__
            },
            "status": "completed",
        }
    )

    result = validate_task_delegation(
        proposal(LAYERS[0], SPECIALISTS[0], parent_task=invalid_parent)
    )
    assert result.allowed is False


def test_result_and_contract_are_immutable():
    result = validate_task_delegation(proposal(GLOBAL, LAYERS[0]))
    with pytest.raises((AttributeError, TypeError)):
        result.allowed = False

    with pytest.raises((AttributeError, TypeError)):
        result.task.status = "completed"


def test_identical_proposals_produce_identical_contracts():
    first = validate_task_delegation(proposal(GLOBAL, LAYERS[0]))
    second = validate_task_delegation(proposal(GLOBAL, LAYERS[0]))

    assert first == second


def test_objective_is_trimmed():
    result = validate_task_delegation(
        proposal(GLOBAL, LAYERS[0], objective="  Review synthetic evidence  ")
    )
    assert result.allowed is True
    assert result.task.objective == "Review synthetic evidence"


def test_invalid_proposal_object_is_rejected():
    result = validate_task_delegation(None)
    assert result.allowed is False


def test_contract_does_not_claim_execution():
    result = validate_task_delegation(proposal(GLOBAL, LAYERS[0]))
    assert result.allowed is True
    assert result.task.status == "proposed"
    assert not hasattr(result.task, "execution_started")
