from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.fortress.registry import get_control
from app.fortress.verifier import (
    EvidenceValidationError,
    VerificationOutcome,
    verify_control,
    verify_controls,
)


CONTROL_ID = "IAM-001"
ORGANIZATION_ID = "org-test-001"


def make_evidence(
    outcomes=None,
    **overrides,
):
    control = get_control(CONTROL_ID)
    now = datetime.now(timezone.utc)

    if outcomes is None:
        outcomes = ["pass"] * len(control.evidence_requirements)

    evidence = {
        "evidence_id": "evidence-test-001",
        "control_id": CONTROL_ID,
        "vault_id": control.vault_id,
        "organization_id": ORGANIZATION_ID,
        "source": "synthetic-test-fixture",
        "collected_at": (now - timedelta(minutes=10)).isoformat(),
        "owner": "test-owner",
        "requirement_results": [
            {
                "requirement_index": index,
                "outcome": outcome,
            }
            for index, outcome in enumerate(outcomes)
        ],
        "review_status": "approved",
        "reviewer": "test-reviewer",
        "reviewed_at": now.isoformat(),
    }

    evidence.update(overrides)
    return evidence


def test_missing_evidence_returns_insufficient_evidence():
    result = verify_control(CONTROL_ID, ORGANIZATION_ID, None)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_unknown_control_is_rejected():
    with pytest.raises(EvidenceValidationError):
        verify_control("UNKNOWN-999", ORGANIZATION_ID, None)


def test_missing_organization_is_rejected():
    with pytest.raises(EvidenceValidationError):
        verify_control(CONTROL_ID, "", None)


def test_valid_approved_evidence_returns_pass():
    result = verify_control(
        CONTROL_ID,
        ORGANIZATION_ID,
        make_evidence(),
    )

    assert result.outcome == VerificationOutcome.PASS
    assert result.vault_id == "identity"
    assert result.evidence_id == "evidence-test-001"


def test_reviewed_failure_returns_fail():
    outcomes = ["pass", "fail"]

    result = verify_control(
        CONTROL_ID,
        ORGANIZATION_ID,
        make_evidence(outcomes=outcomes),
    )

    assert result.outcome == VerificationOutcome.FAIL


def test_unreviewed_failure_returns_review():
    evidence = make_evidence(outcomes=["fail", "pass"])
    evidence.pop("review_status")
    evidence.pop("reviewer")
    evidence.pop("reviewed_at")

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.REVIEW


def test_requirement_review_returns_review():
    result = verify_control(
        CONTROL_ID,
        ORGANIZATION_ID,
        make_evidence(outcomes=["review", "pass"]),
    )

    assert result.outcome == VerificationOutcome.REVIEW


def test_all_not_applicable_with_justification_returns_not_applicable():
    control = get_control(CONTROL_ID)
    evidence = make_evidence(
        outcomes=["not_applicable"] * len(control.evidence_requirements),
        not_applicable_justification="Synthetic test justification.",
    )

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.NOT_APPLICABLE


def test_not_applicable_without_justification_returns_review():
    control = get_control(CONTROL_ID)
    evidence = make_evidence(
        outcomes=["not_applicable"] * len(control.evidence_requirements),
    )

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.REVIEW


def test_wrong_organization_returns_insufficient_evidence():
    evidence = make_evidence()
    evidence["organization_id"] = "another-organization"

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_wrong_vault_returns_insufficient_evidence():
    evidence = make_evidence()
    evidence["vault_id"] = "privilege"

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_wrong_control_returns_insufficient_evidence():
    evidence = make_evidence()
    evidence["control_id"] = "IAM-002"

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_missing_required_field_returns_insufficient_evidence():
    evidence = make_evidence()
    evidence.pop("source")

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_duplicate_requirement_index_returns_insufficient_evidence():
    evidence = make_evidence()
    evidence["requirement_results"][1]["requirement_index"] = 0

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_incomplete_requirement_results_returns_insufficient_evidence():
    evidence = make_evidence()
    evidence["requirement_results"].pop()

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_boolean_requirement_index_is_rejected():
    evidence = make_evidence()
    evidence["requirement_results"][0]["requirement_index"] = True

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_invalid_requirement_outcome_is_rejected():
    evidence = make_evidence()
    evidence["requirement_results"][0]["outcome"] = "success"

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_future_collection_timestamp_is_rejected():
    evidence = make_evidence()
    evidence["collected_at"] = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).isoformat()

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE
    assert "future" in result.reason.lower()


def test_timezone_naive_collection_timestamp_is_rejected():
    evidence = make_evidence()
    evidence["collected_at"] = "2026-11-18T12:00:00"

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_missing_reviewer_returns_review():
    evidence = make_evidence()
    evidence.pop("reviewer")

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.REVIEW


def test_unapproved_review_returns_review():
    evidence = make_evidence()
    evidence["review_status"] = "pending"

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.REVIEW


def test_review_timestamp_before_collection_returns_review():
    evidence = make_evidence()
    collected = datetime.now(timezone.utc) - timedelta(minutes=5)
    reviewed = collected - timedelta(minutes=1)

    evidence["collected_at"] = collected.isoformat()
    evidence["reviewed_at"] = reviewed.isoformat()

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.REVIEW


def test_invalid_review_timestamp_returns_review():
    evidence = make_evidence()
    evidence["reviewed_at"] = "not-a-timestamp"

    result = verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert result.outcome == VerificationOutcome.REVIEW


def test_non_mapping_evidence_returns_insufficient_evidence():
    result = verify_control(CONTROL_ID, ORGANIZATION_ID, [])

    assert result.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_multiple_controls_are_verified_independently():
    second_control = "IAM-002"
    second = make_evidence()
    second["control_id"] = second_control
    second["evidence_id"] = "evidence-test-002"

    results = verify_controls(
        ORGANIZATION_ID,
        {
            CONTROL_ID: make_evidence(),
            second_control: second,
        },
    )

    assert len(results) == 2
    assert all(item.outcome == VerificationOutcome.PASS for item in results)
    assert results[0].control_id == CONTROL_ID
    assert results[1].control_id == second_control


def test_batch_with_invalid_organization_is_rejected():
    with pytest.raises(EvidenceValidationError):
        verify_controls("", {})


def test_batch_with_non_mapping_input_is_rejected():
    with pytest.raises(EvidenceValidationError):
        verify_controls(ORGANIZATION_ID, [])


def test_evidence_input_is_not_mutated():
    evidence = make_evidence()
    original = deepcopy(evidence)

    verify_control(CONTROL_ID, ORGANIZATION_ID, evidence)

    assert evidence == original
