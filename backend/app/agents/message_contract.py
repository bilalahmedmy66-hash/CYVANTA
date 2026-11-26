"""Deterministic, structured, advisory-only agent communication contract."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from app.agents.identity import AgentType, get_agent


MESSAGE_CONTRACT_VERSION = "2.0.0"
MAX_PAYLOAD_DEPTH = 8
MAX_PAYLOAD_NODES = 256
MAX_STRING_LENGTH = 4096
MAX_KEY_LENGTH = 128


class AgentMessageType(str, Enum):
    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    STATUS_UPDATE = "status_update"
    FINDING_REPORT = "finding_report"
    EVIDENCE_SUMMARY = "evidence_summary"
    RECOMMENDATION = "recommendation"
    COORDINATION_NOTICE = "coordination_notice"
    ERROR_REPORT = "error_report"


@dataclass(frozen=True, slots=True)
class MessageProposal:
    message_id: str
    sender_agent_id: str
    receiver_agent_id: str
    message_type: str
    organization_id: str
    tenant_id: str
    correlation_id: str
    created_at: str
    payload: Mapping[str, object]
    task_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgentMessage:
    message_id: str
    contract_version: str
    sender_agent_id: str
    receiver_agent_id: str
    sender_layer_id: str | None
    receiver_layer_id: str | None
    message_type: str
    task_id: str | None
    organization_id: str
    tenant_id: str
    correlation_id: str
    created_at: str
    payload: Mapping[str, object]
    status: str = "validated"


@dataclass(frozen=True, slots=True)
class MessageValidationResult:
    allowed: bool
    reason: str
    message: AgentMessage | None = None
    contract_version: str = MESSAGE_CONTRACT_VERSION


# These are prohibited as message payload field names, including nested fields.
# The communication contract cannot be used to authorize operational behavior.
_FORBIDDEN_KEYS = frozenset({
    "command",
    "commands",
    "shell",
    "shell_command",
    "execute",
    "execution",
    "execute_command",
    "run_command",
    "remediate",
    "remediation",
    "contain",
    "containment",
    "approve",
    "approval",
    "approve_action",
    "emergency_stop",
    "disable_emergency_stop",
    "modify_policy",
    "policy_update",
    "policy_modification",
    "network_operation",
    "scan_asset",
    "asset_scan",
    "worker_activation",
    "activate_worker",
})

_ALLOWED_TYPES = frozenset(item.value for item in AgentMessageType)


def _deny(reason: str) -> MessageValidationResult:
    return MessageValidationResult(allowed=False, reason=reason)


def _valid_text(value: object, maximum: int = 256) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= maximum
    )


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _freeze_json_value(value: object, depth: int, counter: list[int]):
    """Validate and recursively freeze JSON-compatible payload data."""
    counter[0] += 1

    if counter[0] > MAX_PAYLOAD_NODES:
        raise ValueError("Payload contains too many values.")

    if depth > MAX_PAYLOAD_DEPTH:
        raise ValueError("Payload nesting exceeds the allowed depth.")

    if value is None or isinstance(value, (bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite numbers are not valid JSON values.")
        return value

    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise ValueError("Payload string exceeds the allowed length.")
        return value

    if isinstance(value, Mapping):
        frozen = {}

        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Payload object keys must be non-empty strings.")

            if len(key) > MAX_KEY_LENGTH:
                raise ValueError("Payload object key exceeds the allowed length.")

            if _normalize_key(key) in _FORBIDDEN_KEYS:
                raise ValueError(
                    "Payload contains a prohibited operational instruction field."
                )

            frozen[key] = _freeze_json_value(item, depth + 1, counter)

        return MappingProxyType(frozen)

    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json_value(item, depth + 1, counter)
            for item in value
        )

    raise ValueError("Payload contains a non-JSON-compatible value.")


def _parse_timestamp(value: str) -> bool:
    """Require an ISO-8601 timestamp with an explicit timezone."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False

    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _validate_route(sender, receiver) -> bool:
    """Allow communication only between adjacent levels in the hierarchy."""
    if sender.agent_type == AgentType.GLOBAL_COORDINATOR:
        return receiver.agent_type == AgentType.LAYER_COORDINATOR

    if receiver.agent_type == AgentType.GLOBAL_COORDINATOR:
        return sender.agent_type == AgentType.LAYER_COORDINATOR

    if sender.agent_type == AgentType.LAYER_COORDINATOR:
        return (
            receiver.agent_type == AgentType.SPECIALIST
            and sender.layer_id == receiver.layer_id
        )

    if receiver.agent_type == AgentType.LAYER_COORDINATOR:
        return (
            sender.agent_type == AgentType.SPECIALIST
            and sender.layer_id == receiver.layer_id
        )

    # Specialists cannot communicate directly with other specialists.
    return False


def _validate_message_direction(message_type: str, sender, receiver) -> bool:
    """Validate the direction of task requests and task responses."""
    sender_is_higher = (
        sender.agent_type == AgentType.GLOBAL_COORDINATOR
        or (
            sender.agent_type == AgentType.LAYER_COORDINATOR
            and receiver.agent_type == AgentType.SPECIALIST
        )
    )

    if message_type == AgentMessageType.TASK_REQUEST.value:
        return sender_is_higher

    if message_type == AgentMessageType.TASK_RESPONSE.value:
        return not sender_is_higher

    return True


def validate_message(
    proposal: MessageProposal,
    seen_message_ids=(),
) -> MessageValidationResult:
    """Validate a proposed agent message without sending or persisting it."""
    if not isinstance(proposal, MessageProposal):
        return _deny("Invalid message proposal object.")

    required_text = (
        proposal.message_id,
        proposal.sender_agent_id,
        proposal.receiver_agent_id,
        proposal.message_type,
        proposal.organization_id,
        proposal.tenant_id,
        proposal.correlation_id,
        proposal.created_at,
    )

    if not all(_valid_text(value) for value in required_text):
        return _deny("Missing or invalid required message fields.")

    if proposal.task_id is not None and not _valid_text(proposal.task_id):
        return _deny("Invalid task ID.")

    if proposal.sender_agent_id == proposal.receiver_agent_id:
        return _deny("Self-messaging is forbidden.")

    if proposal.message_type not in _ALLOWED_TYPES:
        return _deny("Unsupported message type.")

    if not _parse_timestamp(proposal.created_at):
        return _deny("Timestamp must be valid ISO-8601 with an explicit timezone.")

    if not isinstance(proposal.payload, Mapping) or not proposal.payload:
        return _deny("Payload must be a non-empty structured object.")

    if isinstance(seen_message_ids, (str, bytes)):
        return _deny("Previously seen message IDs must be a collection of IDs.")

    try:
        seen_ids = set(seen_message_ids)
    except (TypeError, ValueError):
        return _deny("Invalid previously seen message ID collection.")

    if proposal.message_id in seen_ids:
        return _deny("Duplicate message ID.")

    try:
        sender = get_agent(proposal.sender_agent_id)
        receiver = get_agent(proposal.receiver_agent_id)
    except (KeyError, ValueError, TypeError):
        return _deny("Unknown sender or receiver agent.")

    if sender.status != "registered" or receiver.status != "registered":
        return _deny("Sender and receiver must both be registered.")

    if (
        sender.permission_profile != "advisory_only"
        or receiver.permission_profile != "advisory_only"
    ):
        return _deny("Only advisory-only agents may exchange messages.")

    if not _validate_route(sender, receiver):
        return _deny(
            "Communication is not permitted by the strict agent hierarchy."
        )

    if not _validate_message_direction(proposal.message_type, sender, receiver):
        return _deny("Message type is not permitted in this communication direction.")

    try:
        frozen_payload = _freeze_json_value(
            proposal.payload,
            depth=0,
            counter=[0],
        )
    except (TypeError, ValueError, RecursionError):
        return _deny("Payload failed structured-data validation.")

    message = AgentMessage(
        message_id=proposal.message_id.strip(),
        contract_version=MESSAGE_CONTRACT_VERSION,
        sender_agent_id=sender.agent_id,
        receiver_agent_id=receiver.agent_id,
        sender_layer_id=sender.layer_id,
        receiver_layer_id=receiver.layer_id,
        message_type=proposal.message_type,
        task_id=proposal.task_id.strip() if proposal.task_id else None,
        organization_id=proposal.organization_id.strip(),
        tenant_id=proposal.tenant_id.strip(),
        correlation_id=proposal.correlation_id.strip(),
        created_at=proposal.created_at,
        payload=frozen_payload,
    )

    return MessageValidationResult(
        allowed=True,
        reason="Structured advisory message validated.",
        message=message,
    )


def validate_message_contract() -> bool:
    """Validate static message-contract configuration."""
    return (
        MESSAGE_CONTRACT_VERSION == "2.0.0"
        and len(_ALLOWED_TYPES) == 8
        and MAX_PAYLOAD_DEPTH > 0
        and MAX_PAYLOAD_NODES > 0
        and MAX_STRING_LENGTH > 0
        and MAX_KEY_LENGTH > 0
        and AgentMessageType.TASK_REQUEST.value in _ALLOWED_TYPES
        and AgentMessageType.TASK_RESPONSE.value in _ALLOWED_TYPES
    )
