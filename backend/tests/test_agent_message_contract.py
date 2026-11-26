import pytest

from app.agents.identity import AGENTS, AgentType
from app.agents.message_contract import (
    MAX_PAYLOAD_DEPTH,
    MESSAGE_CONTRACT_VERSION,
    AgentMessageType,
    MessageProposal,
    validate_message,
    validate_message_contract,
)


GLOBAL = next(
    agent for agent in AGENTS
    if agent.agent_type == AgentType.GLOBAL_COORDINATOR
)
LAYERS = [
    agent for agent in AGENTS
    if agent.agent_type == AgentType.LAYER_COORDINATOR
]
SPECIALISTS = [
    agent for agent in AGENTS
    if agent.agent_type == AgentType.SPECIALIST
]

ORG = "org-message-test"
TENANT = "tenant-message-test"
TIMESTAMP = "2026-11-24T10:00:00+05:30"


def make_message(sender, receiver, **overrides):
    values = {
        "message_id": "message-001",
        "sender_agent_id": sender.agent_id,
        "receiver_agent_id": receiver.agent_id,
        "message_type": AgentMessageType.STATUS_UPDATE.value,
        "organization_id": ORG,
        "tenant_id": TENANT,
        "correlation_id": "correlation-001",
        "created_at": TIMESTAMP,
        "payload": {"summary": "Synthetic analysis complete", "count": 3},
    }
    values.update(overrides)
    return MessageProposal(**values)


def test_static_contract_is_valid():
    assert validate_message_contract() is True
    assert MESSAGE_CONTRACT_VERSION == "2.0.0"
    assert MAX_PAYLOAD_DEPTH == 8


def test_global_can_message_every_layer_coordinator():
    for layer in LAYERS:
        result = validate_message(make_message(GLOBAL, layer))
        assert result.allowed is True


def test_layer_can_message_global_coordinator():
    for layer in LAYERS:
        result = validate_message(make_message(layer, GLOBAL))
        assert result.allowed is True


def test_layer_can_message_its_own_specialists():
    for specialist in SPECIALISTS:
        layer = next(
            item for item in LAYERS
            if item.layer_id == specialist.layer_id
        )
        result = validate_message(make_message(layer, specialist))
        assert result.allowed is True


def test_specialist_can_reply_to_its_own_layer_coordinator():
    for specialist in SPECIALISTS:
        layer = next(
            item for item in LAYERS
            if item.layer_id == specialist.layer_id
        )
        result = validate_message(make_message(specialist, layer))
        assert result.allowed is True


def test_layer_can_send_cross_layer_information_through_global():
    source_layer = LAYERS[0]
    result = validate_message(make_message(source_layer, GLOBAL))
    assert result.allowed is True


def test_global_can_route_information_to_another_layer():
    result = validate_message(make_message(GLOBAL, LAYERS[1]))
    assert result.allowed is True


def test_cross_layer_direct_communication_is_rejected():
    source = LAYERS[0]
    target = LAYERS[1]
    result = validate_message(make_message(source, target))
    assert result.allowed is False


def test_specialist_cannot_message_another_specialist():
    same_layer = [
        item for item in SPECIALISTS
        if item.layer_id == SPECIALISTS[0].layer_id
    ]
    result = validate_message(make_message(same_layer[0], same_layer[1]))
    assert result.allowed is False


def test_specialist_cannot_message_global_directly():
    result = validate_message(make_message(SPECIALISTS[0], GLOBAL))
    assert result.allowed is False


def test_global_cannot_message_specialist_directly():
    result = validate_message(make_message(GLOBAL, SPECIALISTS[0]))
    assert result.allowed is False


def test_self_messaging_is_rejected():
    result = validate_message(make_message(GLOBAL, GLOBAL))
    assert result.allowed is False


def test_task_request_must_flow_down_hierarchy():
    result = validate_message(
        make_message(
            SPECIALISTS[0],
            LAYERS[0],
            message_type=AgentMessageType.TASK_REQUEST.value,
        )
    )
    assert result.allowed is False


def test_task_request_can_flow_from_global_to_layer():
    result = validate_message(
        make_message(
            GLOBAL,
            LAYERS[0],
            message_type=AgentMessageType.TASK_REQUEST.value,
        )
    )
    assert result.allowed is True


def test_task_request_can_flow_from_layer_to_own_specialist():
    specialist = next(
        item for item in SPECIALISTS
        if item.layer_id == LAYERS[0].layer_id
    )
    result = validate_message(
        make_message(
            LAYERS[0],
            specialist,
            message_type=AgentMessageType.TASK_REQUEST.value,
        )
    )
    assert result.allowed is True


def test_task_response_must_flow_up_hierarchy():
    result = validate_message(
        make_message(
            GLOBAL,
            LAYERS[0],
            message_type=AgentMessageType.TASK_RESPONSE.value,
        )
    )
    assert result.allowed is False


def test_task_response_can_flow_from_specialist_to_layer():
    specialist = next(
        item for item in SPECIALISTS
        if item.layer_id == LAYERS[0].layer_id
    )
    result = validate_message(
        make_message(
            specialist,
            LAYERS[0],
            message_type=AgentMessageType.TASK_RESPONSE.value,
        )
    )
    assert result.allowed is True


@pytest.mark.parametrize(
    "message_type",
    [item.value for item in AgentMessageType],
)
def test_all_supported_message_types_are_recognized(message_type):
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], message_type=message_type)
    )
    if message_type == AgentMessageType.TASK_RESPONSE.value:
        assert result.allowed is False
    else:
        assert result.allowed is True


@pytest.mark.parametrize(
    "message_type",
    ["execute", "command", "remediate", "containment", "approve", ""],
)
def test_unsupported_message_types_are_rejected(message_type):
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], message_type=message_type)
    )
    assert result.allowed is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("message_id", ""),
        ("sender_agent_id", ""),
        ("receiver_agent_id", ""),
        ("organization_id", ""),
        ("tenant_id", ""),
        ("correlation_id", ""),
        ("created_at", ""),
    ],
)
def test_missing_required_fields_are_rejected(field, value):
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], **{field: value})
    )
    assert result.allowed is False


def test_unknown_sender_is_rejected():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], sender_agent_id="UNKNOWN-SENDER")
    )
    assert result.allowed is False


def test_unknown_receiver_is_rejected():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], receiver_agent_id="UNKNOWN-RECEIVER")
    )
    assert result.allowed is False


def test_duplicate_message_id_is_rejected_when_seen_ids_are_supplied():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0]),
        seen_message_ids={"message-001", "message-002"},
    )
    assert result.allowed is False


def test_unique_message_id_is_accepted_when_seen_ids_are_supplied():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0]),
        seen_message_ids={"message-previous"},
    )
    assert result.allowed is True


def test_string_is_not_accepted_as_seen_id_collection():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0]),
        seen_message_ids="message-001",
    )
    assert result.allowed is False


def test_payload_must_be_non_empty_mapping():
    for payload in ({}, [], None, "plain text"):
        result = validate_message(
            make_message(GLOBAL, LAYERS[0], payload=payload)
        )
        assert result.allowed is False


@pytest.mark.parametrize(
    "payload",
    [
        {"command": "run"},
        {"shell_command": "anything"},
        {"execute": True},
        {"remediation": {"target": "asset"}},
        {"details": {"emergency_stop": False}},
        {"policy-update": {"enabled": True}},
        {"network_operation": "scan"},
        {"approve_action": True},
    ],
)
def test_prohibited_operational_fields_are_rejected(payload):
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], payload=payload)
    )
    assert result.allowed is False


def test_nested_json_payload_is_accepted():
    payload = {
        "finding": {
            "category": "synthetic",
            "scores": [0.2, 0.8],
            "labels": ["example", "test"],
        },
        "metadata": {"source": "simulation"},
    }
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], payload=payload)
    )
    assert result.allowed is True


def test_payload_is_immutable_after_validation():
    source_payload = {"summary": "original"}
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], payload=source_payload)
    )
    assert result.allowed is True

    source_payload["summary"] = "changed"
    assert result.message.payload["summary"] == "original"

    with pytest.raises(TypeError):
        result.message.payload["summary"] = "modified"


def test_nested_payload_is_immutable():
    result = validate_message(
        make_message(
            GLOBAL,
            LAYERS[0],
            payload={"details": {"labels": ["one", "two"]}},
        )
    )
    assert result.allowed is True

    with pytest.raises(TypeError):
        result.message.payload["details"]["new"] = "value"


def test_non_json_payload_value_is_rejected():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], payload={"invalid": object()})
    )
    assert result.allowed is False


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_rejected(value):
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], payload={"value": value})
    )
    assert result.allowed is False


def test_payload_nesting_limit_is_enforced():
    payload = {"value": "ok"}
    for _ in range(MAX_PAYLOAD_DEPTH + 1):
        payload = {"nested": payload}

    result = validate_message(
        make_message(GLOBAL, LAYERS[0], payload=payload)
    )
    assert result.allowed is False


def test_payload_node_limit_is_enforced():
    payload = {"items": list(range(300))}
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], payload=payload)
    )
    assert result.allowed is False


def test_invalid_timestamp_is_rejected():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], created_at="not-a-timestamp")
    )
    assert result.allowed is False


def test_timestamp_without_timezone_is_rejected():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], created_at="2026-11-24T10:00:00")
    )
    assert result.allowed is False


def test_timestamp_with_z_timezone_is_accepted():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], created_at="2026-11-24T10:00:00Z")
    )
    assert result.allowed is True


def test_task_id_is_optional():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], task_id=None)
    )
    assert result.allowed is True
    assert result.message.task_id is None


def test_empty_task_id_is_rejected():
    result = validate_message(
        make_message(GLOBAL, LAYERS[0], task_id=" ")
    )
    assert result.allowed is False


def test_identical_proposals_produce_identical_results():
    first = validate_message(make_message(GLOBAL, LAYERS[0]))
    second = validate_message(make_message(GLOBAL, LAYERS[0]))
    assert first == second


def test_contract_does_not_claim_to_send_or_execute_messages():
    result = validate_message(make_message(GLOBAL, LAYERS[0]))
    assert result.allowed is True
    assert result.message.status == "validated"
    assert not hasattr(result.message, "sent")
    assert not hasattr(result.message, "execution_started")


def test_invalid_proposal_object_is_rejected():
    result = validate_message(None)
    assert result.allowed is False
