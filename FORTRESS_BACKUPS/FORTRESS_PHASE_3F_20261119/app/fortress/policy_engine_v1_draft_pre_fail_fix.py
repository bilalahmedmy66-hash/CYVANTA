"""Deterministic, fail-closed policy evaluation for CYVANTA FORTRESS V1.0.

This module evaluates supplied verification results against immutable,
tenant-scoped policy definitions. It performs no database, network,
process, execution, remediation, or containment operations.

Approval metadata is validated as supplied data. This module does not
independently authenticate approvers or evidence sources.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from app.fortress.registry import get_control
from app.fortress.verifier import VerificationOutcome, VerificationResult


class PolicyDecisionOutcome(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REVIEW = "REVIEW"
    EXEMPT = "EXEMPT"
    INDETERMINATE = "INDETERMINATE"


class RiskClassification(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class PolicyEvaluationError(ValueError):
    """Raised when policy definitions or evaluation context are invalid."""


@dataclass(frozen=True, slots=True)
class PolicyDefinition:
    policy_id: str
    policy_name: str
    version: str
    control_id: str
    organization_id: str
    enabled: bool
    allowed_verification_outcomes: tuple[VerificationOutcome, ...]
    severity: RiskClassification
    not_applicable_handling: PolicyDecisionOutcome
    exception_policy: bool
    description: str


@dataclass(frozen=True, slots=True)
class PolicyException:
    exception_id: str
    control_id: str
    organization_id: str
    justification: str
    scope: str
    approved_by: str
    approved_at: str
    expires_at: str
    status: str


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision_id: str
    policy_id: str
    policy_version: str
    control_id: str
    layer_id: str
    vault_id: str
    organization_id: str
    verification_outcome: VerificationOutcome
    decision: PolicyDecisionOutcome
    risk: RiskClassification
    reason: str
    evidence_id: str | None
    exception_id: str | None
    recommendation: str


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if not _nonempty_string(value):
        raise PolicyEvaluationError(
            f"{field_name} must be a non-empty ISO-8601 timestamp."
        )

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PolicyEvaluationError(
            f"{field_name} must be a valid ISO-8601 timestamp."
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PolicyEvaluationError(
            f"{field_name} must include a timezone."
        )

    return parsed.astimezone(timezone.utc)


def validate_policy(policy: PolicyDefinition) -> None:
    """Validate one immutable policy definition."""

    if not isinstance(policy, PolicyDefinition):
        raise PolicyEvaluationError("policy must be a PolicyDefinition.")

    for field_name in (
        "policy_id",
        "policy_name",
        "version",
        "control_id",
        "organization_id",
        "description",
    ):
        if not _nonempty_string(getattr(policy, field_name)):
            raise PolicyEvaluationError(
                f"{field_name} must be a non-empty string."
            )

    if type(policy.enabled) is not bool:
        raise PolicyEvaluationError("enabled must be a boolean.")

    if type(policy.exception_policy) is not bool:
        raise PolicyEvaluationError("exception_policy must be a boolean.")

    try:
        control = get_control(policy.control_id)
    except KeyError as exc:
        raise PolicyEvaluationError(
            f"Unknown registered control: {policy.control_id}."
        ) from exc

    if control.status != "active":
        raise PolicyEvaluationError(
            "Policy cannot target an inactive control."
        )

    if control.version != "1.0.0":
        raise PolicyEvaluationError(
            "Control registry version is unsupported."
        )

    if not isinstance(policy.allowed_verification_outcomes, tuple):
        raise PolicyEvaluationError(
            "allowed_verification_outcomes must be a tuple."
        )

    if not policy.allowed_verification_outcomes:
        raise PolicyEvaluationError(
            "At least one allowed verification outcome is required."
        )

    if any(
        not isinstance(item, VerificationOutcome)
        for item in policy.allowed_verification_outcomes
    ):
        raise PolicyEvaluationError(
            "Policy contains an unsupported verification outcome."
        )

    if len(set(policy.allowed_verification_outcomes)) != len(
        policy.allowed_verification_outcomes
    ):
        raise PolicyEvaluationError(
            "Duplicate verification outcomes are not allowed."
        )

    if not isinstance(policy.severity, RiskClassification):
        raise PolicyEvaluationError("Invalid policy severity.")

    if policy.severity == RiskClassification.UNKNOWN:
        raise PolicyEvaluationError(
            "UNKNOWN is a runtime classification, not a policy severity."
        )

    if not isinstance(
        policy.not_applicable_handling,
        PolicyDecisionOutcome,
    ):
        raise PolicyEvaluationError(
            "Invalid NOT_APPLICABLE policy handling."
        )

    if (
        policy.not_applicable_handling
        in (PolicyDecisionOutcome.ALLOW, PolicyDecisionOutcome.EXEMPT)
        and VerificationOutcome.NOT_APPLICABLE
        not in policy.allowed_verification_outcomes
    ):
        raise PolicyEvaluationError(
            "NOT_APPLICABLE handling conflicts with allowed outcomes."
        )


def validate_exception(
    exception: PolicyException,
    organization_id: str,
    control_id: str,
) -> None:
    """Validate an active, approved, tenant- and control-scoped exception."""

    if not isinstance(exception, PolicyException):
        raise PolicyEvaluationError(
            "exception must be a PolicyException."
        )

    for field_name in (
        "exception_id",
        "control_id",
        "organization_id",
        "justification",
        "scope",
        "approved_by",
        "approved_at",
        "expires_at",
    ):
        if not _nonempty_string(getattr(exception, field_name)):
            raise PolicyEvaluationError(
                f"Exception {field_name} must be non-empty."
            )

    if exception.organization_id != organization_id:
        raise PolicyEvaluationError(
            "Exception organization does not match the tenant."
        )

    if exception.control_id != control_id:
        raise PolicyEvaluationError(
            "Exception control scope does not match."
        )

    if exception.scope != f"control:{control_id}":
        raise PolicyEvaluationError(
            "Exception scope must exactly match control:<control_id>."
        )

    if exception.status != "active":
        raise PolicyEvaluationError("Exception is not active.")

    approved_at = _parse_timestamp(
        exception.approved_at, "approved_at"
    )
    expires_at = _parse_timestamp(
        exception.expires_at, "expires_at"
    )
    now = datetime.now(timezone.utc)

    if approved_at > now:
        raise PolicyEvaluationError(
            "Exception approval timestamp cannot be in the future."
        )

    if expires_at <= now:
        raise PolicyEvaluationError("Exception has expired.")

    if expires_at <= approved_at:
        raise PolicyEvaluationError(
            "Exception expiry must follow its approval timestamp."
        )


def classify_risk(
    verification_result: VerificationResult,
    policy: PolicyDefinition,
) -> RiskClassification:
    """Classify risk without modifying the verification result."""

    if not isinstance(verification_result, VerificationResult):
        raise PolicyEvaluationError(
            "verification_result must be a VerificationResult."
        )

    validate_policy(policy)

    outcome = verification_result.outcome

    if outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE:
        return RiskClassification.UNKNOWN

    if outcome == VerificationOutcome.FAIL:
        return policy.severity

    if outcome in (
        VerificationOutcome.REVIEW,
        VerificationOutcome.NOT_APPLICABLE,
    ):
        return RiskClassification.MEDIUM

    if outcome == VerificationOutcome.PASS:
        return RiskClassification.LOW

    return RiskClassification.UNKNOWN


def _decision(
    verification_result: VerificationResult,
    policy: PolicyDefinition,
    outcome: PolicyDecisionOutcome,
    risk: RiskClassification,
    reason: str,
    exception_id: str | None = None,
    recommendation: str = "No automated action is performed.",
) -> PolicyDecision:
    """Build an immutable decision with a deterministic unique input digest."""

    identity = {
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "control_id": verification_result.control_id,
        "organization_id": verification_result.organization_id,
        "verification_outcome": verification_result.outcome.value,
        "evidence_id": verification_result.evidence_id,
        "exception_id": exception_id,
        "decision": outcome.value,
        "risk": risk.value,
    }

    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()

    return PolicyDecision(
        decision_id=f"FORTRESS-{digest}",
        policy_id=policy.policy_id,
        policy_version=policy.version,
        control_id=verification_result.control_id,
        layer_id=verification_result.layer_id,
        vault_id=verification_result.vault_id,
        organization_id=verification_result.organization_id,
        verification_outcome=verification_result.outcome,
        decision=outcome,
        risk=risk,
        reason=reason,
        evidence_id=verification_result.evidence_id,
        exception_id=exception_id,
        recommendation=recommendation,
    )


def _validate_verification_context(
    verification_result: VerificationResult,
    policy: PolicyDefinition,
    organization_id: str,
) -> None:
    """Validate registry and tenant context before policy evaluation."""

    if not isinstance(verification_result, VerificationResult):
        raise PolicyEvaluationError(
            "verification_result must be a VerificationResult."
        )

    if not _nonempty_string(organization_id):
        raise PolicyEvaluationError("organization_id is required.")

    if verification_result.organization_id != organization_id:
        raise PolicyEvaluationError(
            "Verification result organization does not match the tenant."
        )

    if policy.organization_id != organization_id:
        raise PolicyEvaluationError(
            "Policy organization does not match the tenant."
        )

    if verification_result.control_id != policy.control_id:
        raise PolicyEvaluationError(
            "Policy and verification control IDs do not match."
        )

    try:
        control = get_control(verification_result.control_id)
        from app.fortress.vaults import get_vault_for_control
        vault = get_vault_for_control(verification_result.control_id)
    except KeyError as exc:
        raise PolicyEvaluationError(
            "Verification references an unknown control or vault."
        ) from exc

    if control.status != "active":
        raise PolicyEvaluationError(
            "Inactive controls cannot produce policy approval."
        )

    if (
        verification_result.layer_id != control.layer_id
        or verification_result.vault_id != control.vault_id
        or verification_result.vault_id != vault.vault_id
        or verification_result.registry_version != control.version
    ):
        raise PolicyEvaluationError(
            "Verification registry or vault context is inconsistent."
        )

    if (
        not vault.organization_scoped
        or not vault.tenant_isolation_required
    ):
        raise PolicyEvaluationError(
            "Vault does not satisfy mandatory tenant isolation."
        )

    if not isinstance(verification_result.outcome, VerificationOutcome):
        raise PolicyEvaluationError(
            "Verification outcome is unsupported."
        )


def evaluate_control_policy(
    verification_result: VerificationResult,
    policy: PolicyDefinition,
    organization_id: str,
    exception: PolicyException | None = None,
) -> PolicyDecision:
    """Evaluate one verification result against one tenant policy."""

    validate_policy(policy)

    _validate_verification_context(
        verification_result,
        policy,
        organization_id,
    )

    outcome = verification_result.outcome
    risk = classify_risk(verification_result, policy)

    # Insufficient evidence can never be overridden by an exception.
    if outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE:
        if exception is not None:
            raise PolicyEvaluationError(
                "Exceptions cannot override insufficient evidence."
            )

        return _decision(
            verification_result,
            policy,
            PolicyDecisionOutcome.INDETERMINATE,
            RiskClassification.UNKNOWN,
            "Insufficient evidence cannot satisfy policy.",
            recommendation="Obtain valid evidence and repeat verification.",
        )

    if not policy.enabled:
        if exception is not None:
            raise PolicyEvaluationError(
                "Exceptions cannot override a disabled policy."
            )

        return _decision(
            verification_result,
            policy,
            PolicyDecisionOutcome.INDETERMINATE,
            risk,
            "Policy is disabled and cannot produce an approval.",
        )

    # Reject exceptions unless the policy explicitly permits them.
    if exception is not None:
        if not policy.exception_policy:
            raise PolicyEvaluationError(
                "This policy does not permit exceptions."
            )

        validate_exception(
            exception,
            organization_id=organization_id,
            control_id=verification_result.control_id,
        )

        if outcome not in (
            VerificationOutcome.FAIL,
            VerificationOutcome.NOT_APPLICABLE,
        ):
            raise PolicyEvaluationError(
                "Exceptions are only applicable to FAIL or NOT_APPLICABLE outcomes."
            )

    if outcome == VerificationOutcome.REVIEW:
        if exception is not None:
            raise PolicyEvaluationError(
                "Exceptions cannot override a REVIEW outcome."
            )

        return _decision(
            verification_result,
            policy,
            PolicyDecisionOutcome.REVIEW,
            risk,
            "Verification requires human review.",
            recommendation="Complete the required human review.",
        )

    if outcome == VerificationOutcome.FAIL:
        if exception is not None:
            return _decision(
                verification_result,
                policy,
                PolicyDecisionOutcome.EXEMPT,
                risk,
                "A valid explicit exception applies; underlying failure is preserved.",
                exception_id=exception.exception_id,
                recommendation="Monitor the exception until its expiry.",
            )

        return _decision(
            verification_result,
            policy,
            PolicyDecisionOutcome.DENY,
            risk,
            "Verified control failure violates policy.",
            recommendation="Review the violation and determine an approved response.",
        )

    if outcome == VerificationOutcome.NOT_APPLICABLE:
        if (
            outcome not in policy.allowed_verification_outcomes
        ):
            return _decision(
                verification_result,
                policy,
                PolicyDecisionOutcome.REVIEW,
                risk,
                "Policy does not permit NOT_APPLICABLE.",
                recommendation="Review the control applicability.",
            )

        handling = policy.not_applicable_handling

        if handling == PolicyDecisionOutcome.REVIEW:
            if exception is not None:
                raise PolicyEvaluationError(
                    "An exception cannot override NOT_APPLICABLE review handling."
                )

            return _decision(
                verification_result,
                policy,
                PolicyDecisionOutcome.REVIEW,
                risk,
                "Policy requires review for NOT_APPLICABLE.",
            )

        if handling == PolicyDecisionOutcome.DENY:
            if exception is not None:
                raise PolicyEvaluationError(
                    "An exception cannot override explicit NOT_APPLICABLE denial."
                )

            return _decision(
                verification_result,
                policy,
                PolicyDecisionOutcome.DENY,
                risk,
                "Policy denies NOT_APPLICABLE controls.",
            )

        if handling in (
            PolicyDecisionOutcome.ALLOW,
            PolicyDecisionOutcome.EXEMPT,
        ):
            if exception is None:
                return _decision(
                    verification_result,
                    policy,
                    PolicyDecisionOutcome.REVIEW,
                    risk,
                    "NOT_APPLICABLE requires an explicit valid exception.",
                    recommendation="Obtain a scoped, approved, unexpired exception.",
                )

            return _decision(
                verification_result,
                policy,
                PolicyDecisionOutcome.EXEMPT,
                risk,
                "A valid explicit exception covers the NOT_APPLICABLE outcome.",
                exception_id=exception.exception_id,
                recommendation="Monitor the exception until its expiry.",
            )

        raise PolicyEvaluationError(
            "Unsupported NOT_APPLICABLE policy handling."
        )

    if outcome == VerificationOutcome.PASS:
        if exception is not None:
            raise PolicyEvaluationError(
                "An exception cannot be attached to a passing verification."
            )

        if outcome not in policy.allowed_verification_outcomes:
            return _decision(
                verification_result,
                policy,
                PolicyDecisionOutcome.DENY,
                risk,
                "PASS is not permitted by this policy.",
            )

        return _decision(
            verification_result,
            policy,
            PolicyDecisionOutcome.ALLOW,
            risk,
            "Verified outcome satisfies the policy.",
        )

    return _decision(
        verification_result,
        policy,
        PolicyDecisionOutcome.INDETERMINATE,
        RiskClassification.UNKNOWN,
        "No reliable policy decision could be produced.",
    )

