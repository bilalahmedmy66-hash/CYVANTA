"""Deterministic, tenant-isolated, advisory-only agent memory contract."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

from app.agents.identity import AgentType, get_agent


MEMORY_CONTRACT_VERSION = "2.0.0"
DEFAULT_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 30
MAX_MEMORY_PAYLOAD_DEPTH = 8
MAX_MEMORY_PAYLOAD_NODES = 256
MAX_MEMORY_STRING_LENGTH = 4096


class MemoryCategory:
    TASK_CONTEXT = "task_context"
    FINDING = "finding"
    SUMMARY = "summary"
    TEMPORARY_CONTEXT = "temporary_context"


SUPPORTED_MEMORY_CATEGORIES = frozenset({
    MemoryCategory.TASK_CONTEXT,
    MemoryCategory.FINDING,
    MemoryCategory.SUMMARY,
    MemoryCategory.TEMPORARY_CONTEXT,
})


@dataclass(frozen=True, slots=True)
class MemoryProposal:
    memory_id: str
    owner_agent_id: str
    category: str
    organization_id: str
    tenant_id: str
    created_at: str
    payload: Mapping[str, object]
    shared_with: tuple[str, ...] = ()
    retention_days: int = DEFAULT_RETENTION_DAYS
    expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class AgentMemory:
    memory_id: str
    contract_version: str
    owner_agent_id: str
    namespace: str
    category: str
    organization_id: str
    tenant_id: str
    created_at: str
    expires_at: str
    retention_days: int
    shared_with: tuple[str, ...]
    payload: Mapping[str, object]
    trusted_as_instruction: bool = False
    status: str = "active"


@dataclass(frozen=True, slots=True)
class MemoryValidationResult:
    allowed: bool
    reason: str
    memory: AgentMemory | None = None
    contract_version: str = MEMORY_CONTRACT_VERSION


@dataclass(frozen=True, slots=True)
class MemoryAccessResult:
    allowed: bool
    reason: str
    memory_id: str | None = None
    requester_agent_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryDeletionResult:
    allowed: bool
    reason: str
    memory_id: str | None = None
    owner_agent_id: str | None = None


def _valid_text(value: object, maximum: int = 256) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= maximum
    )


def _deny_memory(reason: str) -> MemoryValidationResult:
    return MemoryValidationResult(allowed=False, reason=reason)


def _parse_timestamp(value: object):
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None

    return parsed


def _freeze_payload(value: object, depth: int, counter: list[int]):
    counter[0] += 1

    if counter[0] > MAX_MEMORY_PAYLOAD_NODES:
        raise ValueError("Memory payload contains too many values.")

    if depth > MAX_MEMORY_PAYLOAD_DEPTH:
        raise ValueError("Memory payload nesting exceeds the allowed depth.")

    if value is None or isinstance(value, (bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite numbers are not valid memory values.")
        return value

    if isinstance(value, str):
        if len(value) > MAX_MEMORY_STRING_LENGTH:
            raise ValueError("Memory payload string exceeds the allowed length.")
        return value

    if isinstance(value, Mapping):
        frozen = {}

        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Memory payload keys must be non-empty strings.")

            if len(key) > 128:
                raise ValueError("Memory payload key exceeds the allowed length.")

            frozen[key] = _freeze_payload(item, depth + 1, counter)

        return MappingProxyType(frozen)

    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_payload(item, depth + 1, counter)
            for item in value
        )

    raise ValueError("Memory payload must contain JSON-compatible values.")


def _can_share_between(owner, recipient) -> bool:
    """Require adjacent coordinator hierarchy for explicit memory sharing."""
    if owner.agent_type == AgentType.GLOBAL_COORDINATOR:
        return recipient.agent_type == AgentType.LAYER_COORDINATOR

    if recipient.agent_type == AgentType.GLOBAL_COORDINATOR:
        return owner.agent_type == AgentType.LAYER_COORDINATOR

    if owner.agent_type == AgentType.LAYER_COORDINATOR:
        return (
            recipient.agent_type == AgentType.SPECIALIST
            and owner.layer_id == recipient.layer_id
        )

    if recipient.agent_type == AgentType.LAYER_COORDINATOR:
        return (
            owner.agent_type == AgentType.SPECIALIST
            and owner.layer_id == recipient.layer_id
        )

    return False


def validate_memory_proposal(
    proposal: MemoryProposal,
    existing_memory_ids=(),
) -> MemoryValidationResult:
    """Validate and construct immutable memory metadata without persistence."""
    if not isinstance(proposal, MemoryProposal):
        return _deny_memory("Invalid memory proposal object.")

    required_fields = (
        proposal.memory_id,
        proposal.owner_agent_id,
        proposal.category,
        proposal.organization_id,
        proposal.tenant_id,
        proposal.created_at,
    )

    if not all(_valid_text(value) for value in required_fields):
        return _deny_memory("Missing or invalid required memory fields.")

    if proposal.category not in SUPPORTED_MEMORY_CATEGORIES:
        return _deny_memory("Unsupported memory category.")

    if (
        isinstance(proposal.retention_days, bool)
        or not isinstance(proposal.retention_days, int)
        or not 1 <= proposal.retention_days <= MAX_RETENTION_DAYS
    ):
        return _deny_memory("Retention must be between 1 and 30 days.")

    created_at = _parse_timestamp(proposal.created_at)
    if created_at is None:
        return _deny_memory("Creation timestamp must include a valid timezone.")

    maximum_expiry = created_at + timedelta(days=proposal.retention_days)

    if proposal.expires_at is None:
        expires_at = maximum_expiry
    else:
        expires_at = _parse_timestamp(proposal.expires_at)

        if expires_at is None:
            return _deny_memory("Expiry timestamp must include a valid timezone.")

        if expires_at <= created_at:
            return _deny_memory("Memory expiry must be after creation.")

        if expires_at > maximum_expiry:
            return _deny_memory("Memory expiry exceeds the approved retention period.")

    if not isinstance(proposal.shared_with, tuple):
        return _deny_memory("Sharing recipients must be supplied as a tuple.")

    if len(set(proposal.shared_with)) != len(proposal.shared_with):
        return _deny_memory("Duplicate memory sharing recipients are forbidden.")

    if any(not _valid_text(item) for item in proposal.shared_with):
        return _deny_memory("Invalid memory sharing recipient.")

    if proposal.owner_agent_id in proposal.shared_with:
        return _deny_memory("Memory owner does not need explicit self-sharing.")

    if not isinstance(proposal.payload, Mapping) or not proposal.payload:
        return _deny_memory("Memory payload must be a non-empty structured object.")

    try:
        existing_ids = set(existing_memory_ids)
    except (TypeError, ValueError):
        return _deny_memory("Invalid existing memory ID collection.")

    if isinstance(existing_memory_ids, (str, bytes)):
        return _deny_memory("Existing memory IDs must be supplied as a collection.")

    if proposal.memory_id in existing_ids:
        return _deny_memory("Duplicate memory ID.")

    try:
        owner = get_agent(proposal.owner_agent_id)
    except (KeyError, ValueError, TypeError):
        return _deny_memory("Unknown memory owner agent.")

    if owner.status != "registered":
        return _deny_memory("Memory owner must be registered.")

    if owner.permission_profile != "advisory_only":
        return _deny_memory("Memory owner must have an advisory-only profile.")

    if not _valid_text(owner.memory_namespace):
        return _deny_memory("Memory owner has no valid memory namespace.")

    for recipient_id in proposal.shared_with:
        try:
            recipient = get_agent(recipient_id)
        except (KeyError, ValueError, TypeError):
            return _deny_memory("Unknown memory sharing recipient.")

        if recipient.status != "registered":
            return _deny_memory("Memory recipient must be registered.")

        if recipient.permission_profile != "advisory_only":
            return _deny_memory("Memory recipient must be advisory-only.")

        if not _can_share_between(owner, recipient):
            return _deny_memory(
                "Explicit sharing recipient violates the agent hierarchy."
            )

    try:
        frozen_payload = _freeze_payload(
            proposal.payload,
            depth=0,
            counter=[0],
        )
    except (TypeError, ValueError, RecursionError):
        return _deny_memory("Memory payload failed structured-data validation.")

    memory = AgentMemory(
        memory_id=proposal.memory_id.strip(),
        contract_version=MEMORY_CONTRACT_VERSION,
        owner_agent_id=owner.agent_id,
        namespace=owner.memory_namespace,
        category=proposal.category,
        organization_id=proposal.organization_id.strip(),
        tenant_id=proposal.tenant_id.strip(),
        created_at=created_at.isoformat(),
        expires_at=expires_at.isoformat(),
        retention_days=proposal.retention_days,
        shared_with=proposal.shared_with,
        payload=frozen_payload,
    )

    return MemoryValidationResult(
        allowed=True,
        reason="Memory proposal validated.",
        memory=memory,
    )


def authorize_memory_access(
    memory: AgentMemory,
    requester_agent_id: str,
    organization_id: str,
    tenant_id: str,
    at_time: str,
) -> MemoryAccessResult:
    """Authorize owner or explicitly named recipient to retrieve memory."""
    if not isinstance(memory, AgentMemory):
        return MemoryAccessResult(False, "Invalid memory record.")

    if not _valid_text(requester_agent_id):
        return MemoryAccessResult(False, "Invalid requester identity.")

    if not _valid_text(organization_id) or not _valid_text(tenant_id):
        return MemoryAccessResult(False, "Organization and tenant scope are required.")

    if (
        organization_id != memory.organization_id
        or tenant_id != memory.tenant_id
    ):
        return MemoryAccessResult(False, "Memory organization or tenant scope mismatch.")

    current_time = _parse_timestamp(at_time)
    expiry_time = _parse_timestamp(memory.expires_at)

    if current_time is None or expiry_time is None:
        return MemoryAccessResult(False, "Invalid retrieval or expiry timestamp.")

    if current_time >= expiry_time:
        return MemoryAccessResult(False, "Memory has expired.")

    if memory.status != "active":
        return MemoryAccessResult(False, "Memory is not active.")

    try:
        requester = get_agent(requester_agent_id)
    except (KeyError, ValueError, TypeError):
        return MemoryAccessResult(False, "Unknown requester agent.")

    if requester.status != "registered":
        return MemoryAccessResult(False, "Requester must be registered.")

    if requester.permission_profile != "advisory_only":
        return MemoryAccessResult(False, "Requester must be advisory-only.")

    if requester.agent_id != memory.owner_agent_id:
        if requester.agent_id not in memory.shared_with:
            return MemoryAccessResult(
                False,
                "Memory access requires explicit owner-authorized sharing.",
            )

    return MemoryAccessResult(
        True,
        "Memory retrieval authorized.",
        memory_id=memory.memory_id,
        requester_agent_id=requester.agent_id,
    )


def authorize_memory_deletion(
    memory: AgentMemory,
    requester_agent_id: str,
    organization_id: str,
    tenant_id: str,
) -> MemoryDeletionResult:
    """Authorize deletion requests only from the owning agent identity."""
    if not isinstance(memory, AgentMemory):
        return MemoryDeletionResult(False, "Invalid memory record.")

    if not _valid_text(requester_agent_id):
        return MemoryDeletionResult(False, "Invalid deletion requester.")

    if (
        not _valid_text(organization_id)
        or not _valid_text(tenant_id)
        or organization_id != memory.organization_id
        or tenant_id != memory.tenant_id
    ):
        return MemoryDeletionResult(
            False,
            "Memory organization or tenant scope mismatch.",
        )

    if requester_agent_id != memory.owner_agent_id:
        return MemoryDeletionResult(
            False,
            "Only the owning agent may authorize memory deletion.",
        )

    try:
        owner = get_agent(requester_agent_id)
    except (KeyError, ValueError, TypeError):
        return MemoryDeletionResult(False, "Unknown memory owner.")

    if owner.status != "registered":
        return MemoryDeletionResult(False, "Memory owner must be registered.")

    return MemoryDeletionResult(
        True,
        "Memory deletion authorized by its owner.",
        memory_id=memory.memory_id,
        owner_agent_id=owner.agent_id,
    )


def is_memory_expired(memory: AgentMemory, at_time: str) -> bool:
    """Return expiry state using an explicit timezone-aware timestamp."""
    if not isinstance(memory, AgentMemory):
        return True

    current_time = _parse_timestamp(at_time)
    expiry_time = _parse_timestamp(memory.expires_at)

    if current_time is None or expiry_time is None:
        return True

    return current_time >= expiry_time


def validate_memory_contract() -> bool:
    """Validate static memory contract configuration."""
    return (
        MEMORY_CONTRACT_VERSION == "2.0.0"
        and DEFAULT_RETENTION_DAYS == 30
        and MAX_RETENTION_DAYS == 30
        and len(SUPPORTED_MEMORY_CATEGORIES) == 4
        and MAX_MEMORY_PAYLOAD_DEPTH > 0
        and MAX_MEMORY_PAYLOAD_NODES > 0
        and MAX_MEMORY_STRING_LENGTH > 0
    )
