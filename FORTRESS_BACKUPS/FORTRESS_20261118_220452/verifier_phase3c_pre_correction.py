"""Deterministic, fail-closed evidence verification for CYVANTA FORTRESS V1.0.

This module evaluates supplied structured evidence only.
It does not authenticate evidence sources, access external systems,
perform scans, contact networks, or execute operational actions.

PASS means the supplied evidence requirements have an approved review
record. It is not an independent guarantee of external system security.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from app.fortress.registry import get_control
from app.fortress.vaults import get_vault_for_control


class VerificationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvidenceValidationError(ValueError):
    """Raised when evidence structure or tenant context is invalid."""


@dataclass(frozen=True, slots=True)
class VerificationResult:
    control_id: str
    layer_id: str
    vault_id: str
    organization_id: str
    outcome: VerificationOutcome
    reason: str
    evidence_id: str | None
    registry_version: str


_ALLOWED_REQUIREMENT_OUTCOMES = frozenset(
    {"pass", "fail", "review", "not_applicable"}
)

_REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
        "evidence_id",
        "control_id",
        "vault_id",
        "organization_id",
        "source",
        "collected_at",
        "owner",
        "requirement_results",
    }
)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if not _nonempty_string(value):
        raise EvidenceValidationError(
            f"{field_name} must be a non-empty ISO-8601 timestamp."
        )

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError(
            f"{field_name} is not a valid ISO-8601 timestamp."
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceValidationError(
            f"{field_name} must include a timezone."
        )

    return parsed.astimezone(timezone.utc)


def _validate_context(
    control_id: str,
    organization_id: str,
) -> tuple[Any, Any]:
    if not _nonempty_string(control_id):
        raise EvidenceValidationError("control_id is required.")

    if not _nonempty_string(organization_id):
        raise EvidenceValidationError("organization_id is required.")

    try:
        control = get_control(control_id)
        vault = get_vault_for_control(control_id)
    except KeyError as exc:
        raise EvidenceValidationError(
            f"Unknown registered control: {control_id}."
        ) from exc

    if control.vault_id != vault.vault_id:
        raise EvidenceValidationError(
            "Control and vault registry mappings do not match."
        )

    if not vault.organization_scoped or not vault.tenant_isolation_required:
        raise EvidenceValidationError(
            "Vault does not satisfy mandatory tenant isolation."
        )

    return control, vault


def _validate_evidence(
    evidence: Mapping[str, Any],
    control_id: str,
    organization_id: str,
    vault_id: str,
    requirement_count: int,
) -> list[str]:
    if not isinstance(evidence, Mapping):
        raise EvidenceValidationError("Evidence must be a mapping.")

    missing = _REQUIRED_EVIDENCE_FIELDS.difference(evidence.keys())
    if missing:
        raise EvidenceValidationError(
            "Evidence is missing required fields: "
            + ", ".join(sorted(missing))
        )

    for field in ("evidence_id", "control_id", "vault_id",
                  "organization_id", "source", "owner"):
        if not _nonempty_string(evidence.get(field)):
            raise EvidenceValidationError(
                f"{field} must be a non-empty string."
            )

    if evidence["control_id"] != control_id:
        raise EvidenceValidationError("Evidence control_id mismatch.")

    if evidence["vault_id"] != vault_id:
        raise EvidenceValidationError("Evidence vault_id mismatch.")

    if evidence["organization_id"] != organization_id:
        raise EvidenceValidationError(
            "Evidence organization_id does not match the requested tenant."
        )

    _parse_timestamp(evidence["collected_at"], "collected_at")

    results = evidence["requirement_results"]
    if not isinstance(results, (list, tuple)):
        raise EvidenceValidationError(
            "requirement_results must be a list or tuple."
        )

    normalized: dict[int, str] = {}

    for item in results:
        if not isinstance(item, Mapping):
            raise EvidenceValidationError(
                "Every requirement result must be a mapping."
            )

        index = item.get("requirement_index")
        outcome = item.get("outcome")

        if isinstance(index, bool) or not isinstance(index, int):
            raise EvidenceValidationError(
                "requirement_index must be an integer."
            )

        if index < 0 or index >= requirement_count:
            raise EvidenceValidationError(
                "requirement_index is outside the registered requirements."
            )

        if index in normalized:
            raise EvidenceValidationError(
                "Duplicate requirement_index detected."
            )

        if not isinstance(outcome, str) or outcome not in _ALLOWED_REQUIREMENT_OUTCOMES:
            raise EvidenceValidationError(
                "Unsupported requirement outcome."
            )

        normalized[index] = outcome

    if len(normalized) != requirement_count:
        raise EvidenceValidationError(
            "Evidence does not address every registered requirement."
        )

    return [normalized[index] for index in range(requirement_count)]


def verify_control(
    control_id: str,
    organization_id: str,
    evidence: Mapping[str, Any] | None,
) -> VerificationResult:
    """Evaluate one control against supplied, tenant-scoped evidence.

    Evidence outcomes are recorded assessment claims. PASS and
    NOT_APPLICABLE require an approved human review record.
    Invalid evidence fails closed as INSUFFICIENT_EVIDENCE.
    """

    control, vault = _validate_context(control_id, organization_id)

    def result(
        outcome: VerificationOutcome,
        reason: str,
        evidence_id: str | None = None,
    ) -> VerificationResult:
        return VerificationResult(
            control_id=control.control_id,
            layer_id=control.layer_id,
            vault_id=vault.vault_id,
            organization_id=organization_id,
            outcome=outcome,
            reason=reason,
            evidence_id=evidence_id,
            registry_version=control.version,
        )

    if evidence is None:
        return result(
            VerificationOutcome.INSUFFICIENT_EVIDENCE,
            "No evidence was supplied.",
        )

    try:
        outcomes = _validate_evidence(
            evidence=evidence,
            control_id=control_id,
            organization_id=organization_id,
            vault_id=vault.vault_id,
            requirement_count=len(control.evidence_requirements),
        )
    except EvidenceValidationError as exc:
        return result(
            VerificationOutcome.INSUFFICIENT_EVIDENCE,
            str(exc),
            evidence.get("evidence_id")
            if isinstance(evidence, Mapping)
            and _nonempty_string(evidence.get("evidence_id"))
            else None,
        )

    evidence_id = evidence["evidence_id"]

    if "fail" in outcomes:
        return result(
            VerificationOutcome.FAIL,
            "At least one supplied requirement assessment records a failure.",
            evidence_id,
        )

    if "review" in outcomes:
        return result(
            VerificationOutcome.REVIEW,
            "At least one requirement needs further review.",
            evidence_id,
        )

    review_status = evidence.get("review_status")
    reviewer = evidence.get("reviewer")
    reviewed_at = evidence.get("reviewed_at")

    if not all(
        (
            review_status == "approved",
            _nonempty_string(reviewer),
            _nonempty_string(reviewed_at),
        )
    ):
        return result(
            VerificationOutcome.REVIEW,
            "Requirement results lack a complete approved reviewer record.",
            evidence_id,
        )

    try:
        reviewed_timestamp = _parse_timestamp(reviewed_at, "reviewed_at")
    except EvidenceValidationError as exc:
        return result(
            VerificationOutcome.REVIEW,
            str(exc),
            evidence_id,
        )

    if reviewed_timestamp < _parse_timestamp(
        evidence["collected_at"], "collected_at"
    ):
        return result(
            VerificationOutcome.REVIEW,
            "Review timestamp predates evidence collection.",
            evidence_id,
        )

    if all(outcome == "not_applicable" for outcome in outcomes):
        if not _nonempty_string(evidence.get("not_applicable_justification")):
            return result(
                VerificationOutcome.REVIEW,
                "Not-applicable assessment requires a documented justification.",
                evidence_id,
            )

        return result(
            VerificationOutcome.NOT_APPLICABLE,
            "All requirements were reviewed and marked not applicable.",
            evidence_id,
        )

    if all(outcome == "pass" for outcome in outcomes):
        return result(
            VerificationOutcome.PASS,
            "All registered requirements have passing results and an approved review record.",
            evidence_id,
        )

    return result(
        VerificationOutcome.REVIEW,
        "Requirement outcomes are mixed and need human review.",
        evidence_id,
    )


def verify_controls(
    organization_id: str,
    evidence_by_control: Mapping[str, Mapping[str, Any] | None],
) -> tuple[VerificationResult, ...]:
    """Verify supplied controls independently for one organization."""

    if not _nonempty_string(organization_id):
        raise EvidenceValidationError("organization_id is required.")

    if not isinstance(evidence_by_control, Mapping):
        raise EvidenceValidationError(
            "evidence_by_control must be a mapping."
        )

    results = []

    for control_id in evidence_by_control:
        results.append(
            verify_control(
                control_id=control_id,
                organization_id=organization_id,
                evidence=evidence_by_control[control_id],
            )
        )

    return tuple(results)
