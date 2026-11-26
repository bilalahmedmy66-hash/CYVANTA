from datetime import datetime, timedelta, timezone

import pytest

from app.fortress.registry import get_control
from app.fortress.verifier import (
    VerificationOutcome,
    verify_control,
)
from app.fortress.policy_engine import (
    PolicyDecisionOutcome,
    PolicyDefinition,
    PolicyEvaluationError,
    RiskClassification,
    evaluate_control_policy,
)


CONTROL_ID = "IAM-001"
ORGANIZATION_ID = "org-test-001"


def make_evidence(requirement_outcomes=None):
    control = get_control(CONTROL_ID)
    now = datetime.now(timezone.utc)

    if requirement_outcomes is None:
        requirement_outcomes = [
            "pass"
        ] * len(control.evidence_requirements)

    return {
        "evidence_id": "integration-evidence-001",
        "control_id": CONTROL_ID,
        "vault_id": control.vault_id,
        "organization_id": ORGANIZATION_ID,
        "source": "synthetic-integration-test",
        "collected_at": (now - timedelta(minutes=10)).isoformat(),
        "owner": "integration-test-owner",
        "requirement_results": [
            {
                "requirement_index": index,
                "outcome": outcome,
            }
            for index, outcome in enumerate(requirement_outcomes)
        ],
        "review_status": "approved",
        "reviewer": "integration-test-reviewer",
        "reviewed_at": now.isoformat(),
    }


def make_policy(organization_id=ORGANIZATION_ID):
    return PolicyDefinition(
        policy_id="POL-IAM-001",
        policy_name="Integration Identity Policy",
        version="1.0.0",
        control_id=CONTROL_ID,
        organization_id=organization_id,
        enabled=True,
        allowed_verification_outcomes=tuple(VerificationOutcome),
        severity=RiskClassification.HIGH,
        not_applicable_handling=PolicyDecisionOutcome.REVIEW,
        exception_policy=True,
        description="Synthetic integration test policy.",
    )


def test_approved_passing_evidence_produces_allow():
    verification = verify_control(
        CONTROL_ID,
        ORGANIZATION_ID,
        make_evidence(),
    )

    assert verification.outcome == VerificationOutcome.PASS

    decision = evaluate_control_policy(
        verification,
        make_policy(),
        ORGANIZATION_ID,
    )

    assert decision.decision == PolicyDecisionOutcome.ALLOW
    assert decision.verification_outcome == VerificationOutcome.PASS
    assert decision.evidence_id == "integration-evidence-001"


def test_reviewed_failing_evidence_produces_deny():
    control = get_control(CONTROL_ID)
    outcomes = ["pass"] * len(control.evidence_requirements)
    outcomes[0] = "fail"

    verification = verify_control(
        CONTROL_ID,
        ORGANIZATION_ID,
        make_evidence(outcomes),
    )

    assert verification.outcome == VerificationOutcome.FAIL

    decision = evaluate_control_policy(
        verification,
        make_policy(),
        ORGANIZATION_ID,
    )

    assert decision.decision == PolicyDecisionOutcome.DENY
    assert decision.verification_outcome == VerificationOutcome.FAIL
    assert decision.risk == RiskClassification.HIGH


def test_missing_evidence_produces_indeterminate():
    verification = verify_control(
        CONTROL_ID,
        ORGANIZATION_ID,
        None,
    )

    assert verification.outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE

    decision = evaluate_control_policy(
        verification,
        make_policy(),
        ORGANIZATION_ID,
    )

    assert decision.decision == PolicyDecisionOutcome.INDETERMINATE
    assert decision.verification_outcome == VerificationOutcome.INSUFFICIENT_EVIDENCE
    assert decision.risk == RiskClassification.UNKNOWN


def test_cross_tenant_policy_evaluation_is_rejected():
    verification = verify_control(
        CONTROL_ID,
        ORGANIZATION_ID,
        make_evidence(),
    )

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            verification,
            make_policy(organization_id="org-other-002"),
            "org-other-002",
        )
