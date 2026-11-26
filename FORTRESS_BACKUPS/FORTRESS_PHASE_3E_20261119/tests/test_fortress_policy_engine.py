from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.fortress.registry import get_control
from app.fortress.verifier import VerificationOutcome, VerificationResult
from app.fortress.policy_engine import (
    PolicyDecisionOutcome,
    PolicyDefinition,
    PolicyEvaluationError,
    PolicyException,
    RiskClassification,
    classify_risk,
    validate_exception,
    validate_policy,
)


CONTROL_ID = "IAM-001"
ORGANIZATION_ID = "org-test-001"


def make_policy(**overrides):
    values = {
        "policy_id": "POL-IAM-001",
        "policy_name": "Identity Inventory Policy",
        "version": "1.0.0",
        "control_id": CONTROL_ID,
        "organization_id": ORGANIZATION_ID,
        "enabled": True,
        "allowed_verification_outcomes": tuple(VerificationOutcome),
        "severity": RiskClassification.HIGH,
        "not_applicable_handling": PolicyDecisionOutcome.REVIEW,
        "exception_policy": True,
        "description": "Synthetic policy test fixture.",
    }
    values.update(overrides)
    return PolicyDefinition(**values)


def make_verification(outcome=VerificationOutcome.PASS, **overrides):
    control = get_control(CONTROL_ID)

    values = {
        "control_id": CONTROL_ID,
        "layer_id": control.layer_id,
        "vault_id": control.vault_id,
        "organization_id": ORGANIZATION_ID,
        "outcome": outcome,
        "reason": "Synthetic verification result.",
        "evidence_id": "evidence-test-001",
        "registry_version": control.version,
    }
    values.update(overrides)
    return VerificationResult(**values)


def make_exception(**overrides):
    now = datetime.now(timezone.utc)

    values = {
        "exception_id": "EXC-IAM-001",
        "control_id": CONTROL_ID,
        "organization_id": ORGANIZATION_ID,
        "justification": "Synthetic approved exception for testing.",
        "scope": f"control:{CONTROL_ID}",
        "approved_by": "synthetic-test-approver",
        "approved_at": (now - timedelta(minutes=5)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "status": "active",
    }
    values.update(overrides)
    return PolicyException(**values)



def test_valid_policy_passes_validation():
    assert validate_policy(make_policy()) is None


def test_unknown_control_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_policy(make_policy(control_id="UNKNOWN-999"))


def test_empty_policy_name_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_policy(make_policy(policy_name=" "))


def test_empty_allowed_outcomes_are_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_policy(make_policy(allowed_verification_outcomes=()))


def test_duplicate_allowed_outcomes_are_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_policy(
            make_policy(
                allowed_verification_outcomes=(
                    VerificationOutcome.PASS,
                    VerificationOutcome.PASS,
                )
            )
        )


def test_unknown_policy_severity_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_policy(
            make_policy(severity=RiskClassification.UNKNOWN)
        )


def test_not_applicable_allow_requires_allowed_outcome():
    with pytest.raises(PolicyEvaluationError):
        validate_policy(
            make_policy(
                allowed_verification_outcomes=(VerificationOutcome.PASS,),
                not_applicable_handling=PolicyDecisionOutcome.ALLOW,
            )
        )


def test_policy_is_immutable():
    policy = make_policy()

    with pytest.raises(FrozenInstanceError):
        policy.enabled = False


@pytest.mark.parametrize(
    ("verification_outcome", "expected_risk"),
    [
        (VerificationOutcome.PASS, RiskClassification.LOW),
        (VerificationOutcome.FAIL, RiskClassification.HIGH),
        (VerificationOutcome.REVIEW, RiskClassification.MEDIUM),
        (
            VerificationOutcome.NOT_APPLICABLE,
            RiskClassification.MEDIUM,
        ),
        (
            VerificationOutcome.INSUFFICIENT_EVIDENCE,
            RiskClassification.UNKNOWN,
        ),
    ],
)
def test_risk_classification(
    verification_outcome,
    expected_risk,
):
    result = make_verification(verification_outcome)

    assert classify_risk(result, make_policy()) == expected_risk


def test_fail_risk_uses_policy_severity():
    result = make_verification(VerificationOutcome.FAIL)

    policy = make_policy(severity=RiskClassification.MEDIUM)

    assert classify_risk(result, policy) == RiskClassification.MEDIUM




def test_valid_exception_passes_validation():
    exception = make_exception()

    assert validate_exception(
        exception,
        ORGANIZATION_ID,
        CONTROL_ID,
    ) is None


def test_exception_wrong_organization_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(organization_id="another-org"),
            ORGANIZATION_ID,
            CONTROL_ID,
        )


def test_exception_wrong_control_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(control_id="IAM-002"),
            ORGANIZATION_ID,
            CONTROL_ID,
        )


def test_exception_wildcard_scope_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(scope="*"),
            ORGANIZATION_ID,
            CONTROL_ID,
        )


def test_inactive_exception_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(status="inactive"),
            ORGANIZATION_ID,
            CONTROL_ID,
        )


def test_exception_without_justification_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(justification=" "),
            ORGANIZATION_ID,
            CONTROL_ID,
        )


def test_exception_without_approver_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(approved_by=" "),
            ORGANIZATION_ID,
            CONTROL_ID,
        )


def test_expired_exception_is_rejected():
    past = datetime.now(timezone.utc) - timedelta(hours=2)

    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(
                approved_at=(past - timedelta(hours=1)).isoformat(),
                expires_at=past.isoformat(),
            ),
            ORGANIZATION_ID,
            CONTROL_ID,
        )


def test_future_approval_timestamp_is_rejected():
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(approved_at=future.isoformat()),
            ORGANIZATION_ID,
            CONTROL_ID,
        )


def test_timezone_naive_approval_timestamp_is_rejected():
    naive = datetime.now().isoformat()

    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(approved_at=naive),
            ORGANIZATION_ID,
            CONTROL_ID,
        )


def test_invalid_expiry_timestamp_is_rejected():
    with pytest.raises(PolicyEvaluationError):
        validate_exception(
            make_exception(expires_at="not-a-timestamp"),
            ORGANIZATION_ID,
            CONTROL_ID,
        )




def test_pass_produces_allow():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.PASS)

    decision = evaluate_control_policy(
        result,
        make_policy(),
        ORGANIZATION_ID,
    )

    assert decision.decision == PolicyDecisionOutcome.ALLOW
    assert decision.verification_outcome == VerificationOutcome.PASS


def test_fail_produces_deny():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.FAIL)

    decision = evaluate_control_policy(
        result,
        make_policy(),
        ORGANIZATION_ID,
    )

    assert decision.decision == PolicyDecisionOutcome.DENY
    assert decision.risk == RiskClassification.HIGH


def test_fail_with_valid_exception_produces_exempt():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.FAIL)
    exception = make_exception()

    decision = evaluate_control_policy(
        result,
        make_policy(),
        ORGANIZATION_ID,
        exception,
    )

    assert decision.decision == PolicyDecisionOutcome.EXEMPT
    assert decision.verification_outcome == VerificationOutcome.FAIL
    assert decision.exception_id == exception.exception_id


def test_review_produces_review():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.REVIEW)

    decision = evaluate_control_policy(
        result,
        make_policy(),
        ORGANIZATION_ID,
    )

    assert decision.decision == PolicyDecisionOutcome.REVIEW


def test_insufficient_evidence_produces_indeterminate():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.INSUFFICIENT_EVIDENCE
    )

    decision = evaluate_control_policy(
        result,
        make_policy(),
        ORGANIZATION_ID,
    )

    assert decision.decision == PolicyDecisionOutcome.INDETERMINATE
    assert decision.risk == RiskClassification.UNKNOWN


def test_not_applicable_without_exception_requires_review():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.NOT_APPLICABLE
    )

    policy = make_policy(
        not_applicable_handling=PolicyDecisionOutcome.ALLOW,
    )

    decision = evaluate_control_policy(
        result,
        policy,
        ORGANIZATION_ID,
    )

    assert decision.decision == PolicyDecisionOutcome.REVIEW


def test_not_applicable_with_valid_exception_produces_exempt():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.NOT_APPLICABLE
    )

    policy = make_policy(
        not_applicable_handling=PolicyDecisionOutcome.ALLOW,
    )

    exception = make_exception()

    decision = evaluate_control_policy(
        result,
        policy,
        ORGANIZATION_ID,
        exception,
    )

    assert decision.decision == PolicyDecisionOutcome.EXEMPT
    assert decision.verification_outcome == VerificationOutcome.NOT_APPLICABLE


def test_disabled_policy_produces_indeterminate():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.PASS)

    decision = evaluate_control_policy(
        result,
        make_policy(enabled=False),
        ORGANIZATION_ID,
    )

    assert decision.decision == PolicyDecisionOutcome.INDETERMINATE




def test_exception_cannot_override_insufficient_evidence():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.INSUFFICIENT_EVIDENCE
    )

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            make_policy(),
            ORGANIZATION_ID,
            make_exception(),
        )


def test_exception_cannot_override_review():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.REVIEW)

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            make_policy(),
            ORGANIZATION_ID,
            make_exception(),
        )


def test_exception_cannot_override_pass():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.PASS)

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            make_policy(),
            ORGANIZATION_ID,
            make_exception(),
        )


def test_exception_cannot_override_disabled_policy():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.FAIL)

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            make_policy(enabled=False),
            ORGANIZATION_ID,
            make_exception(),
        )


def test_exception_rejected_when_fail_is_not_allowed():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.FAIL)

    policy = make_policy(
        allowed_verification_outcomes=(VerificationOutcome.PASS,),
    )

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            policy,
            ORGANIZATION_ID,
            make_exception(),
        )


def test_exception_rejected_when_not_applicable_is_not_allowed():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.NOT_APPLICABLE
    )

    policy = make_policy(
        allowed_verification_outcomes=(VerificationOutcome.PASS,),
        not_applicable_handling=PolicyDecisionOutcome.REVIEW,
    )

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            policy,
            ORGANIZATION_ID,
            make_exception(),
        )


@pytest.mark.parametrize(
    "handling",
    [
        PolicyDecisionOutcome.REVIEW,
        PolicyDecisionOutcome.DENY,
    ],
)
def test_exception_cannot_override_not_applicable_review_or_deny(handling):
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.NOT_APPLICABLE
    )

    policy = make_policy(not_applicable_handling=handling)

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            policy,
            ORGANIZATION_ID,
            make_exception(),
        )




def test_cross_tenant_verification_is_rejected():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.PASS,
        organization_id="another-organization",
    )

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            make_policy(),
            ORGANIZATION_ID,
        )


def test_cross_tenant_policy_is_rejected():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.PASS)

    policy = make_policy(organization_id="another-organization")

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            policy,
            ORGANIZATION_ID,
        )


def test_mismatched_control_is_rejected():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.PASS,
        control_id="IAM-002",
    )

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            make_policy(),
            ORGANIZATION_ID,
        )


def test_mismatched_vault_is_rejected():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.PASS,
        vault_id="privilege",
    )

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            make_policy(),
            ORGANIZATION_ID,
        )


def test_mismatched_registry_version_is_rejected():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(
        VerificationOutcome.PASS,
        registry_version="9.9.9",
    )

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            result,
            make_policy(),
            ORGANIZATION_ID,
        )


def test_invalid_verification_object_is_rejected():
    from app.fortress.policy_engine import evaluate_control_policy

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(
            object(),
            make_policy(),
            ORGANIZATION_ID,
        )




def make_second_control_fixtures():
    control_id = "IAM-002"
    control = get_control(control_id)

    result = VerificationResult(
        control_id=control_id,
        layer_id=control.layer_id,
        vault_id=control.vault_id,
        organization_id=ORGANIZATION_ID,
        outcome=VerificationOutcome.PASS,
        reason="Synthetic second-control verification.",
        evidence_id="evidence-test-002",
        registry_version=control.version,
    )

    policy = make_policy(
        policy_id="POL-IAM-002",
        policy_name="Identity Proofing Policy",
        control_id=control_id,
    )

    return result, policy


def test_batch_evaluation_returns_decisions_for_multiple_controls():
    from app.fortress.policy_engine import evaluate_policy

    second_result, second_policy = make_second_control_fixtures()

    decisions = evaluate_policy(
        ORGANIZATION_ID,
        [
            make_verification(VerificationOutcome.PASS),
            second_result,
        ],
        [
            make_policy(),
            second_policy,
        ],
    )

    assert len(decisions) == 2
    assert isinstance(decisions, tuple)
    assert all(
        decision.decision == PolicyDecisionOutcome.ALLOW
        for decision in decisions
    )


def test_batch_missing_policy_is_rejected():
    from app.fortress.policy_engine import evaluate_policy

    with pytest.raises(PolicyEvaluationError):
        evaluate_policy(
            ORGANIZATION_ID,
            [make_verification()],
            [],
        )


def test_batch_duplicate_policy_id_is_rejected():
    from app.fortress.policy_engine import evaluate_policy

    first = make_policy()
    second = make_policy(control_id="IAM-002")

    with pytest.raises(PolicyEvaluationError):
        evaluate_policy(
            ORGANIZATION_ID,
            [],
            [
                first,
                second.__class__(
                    **{
                        **{
                            field: getattr(second, field)
                            for field in second.__dataclass_fields__
                        },
                        "policy_id": first.policy_id,
                    }
                ),
            ],
        )


def test_batch_duplicate_control_policy_is_rejected():
    from app.fortress.policy_engine import evaluate_policy

    first = make_policy()
    second = make_policy(policy_id="POL-IAM-001-SECOND")

    with pytest.raises(PolicyEvaluationError):
        evaluate_policy(
            ORGANIZATION_ID,
            [],
            [first, second],
        )


def test_batch_duplicate_verification_result_is_rejected():
    from app.fortress.policy_engine import evaluate_policy

    result = make_verification()

    with pytest.raises(PolicyEvaluationError):
        evaluate_policy(
            ORGANIZATION_ID,
            [result, result],
            [make_policy()],
        )


def test_batch_cross_tenant_policy_is_rejected():
    from app.fortress.policy_engine import evaluate_policy

    with pytest.raises(PolicyEvaluationError):
        evaluate_policy(
            ORGANIZATION_ID,
            [],
            [make_policy(organization_id="another-org")],
        )


def test_batch_unused_exception_is_rejected():
    from app.fortress.policy_engine import evaluate_policy

    with pytest.raises(PolicyEvaluationError):
        evaluate_policy(
            ORGANIZATION_ID,
            [],
            [make_policy()],
            [make_exception()],
        )




def test_identical_inputs_produce_identical_decision_ids():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.PASS)
    policy = make_policy()

    first = evaluate_control_policy(result, policy, ORGANIZATION_ID)
    second = evaluate_control_policy(result, policy, ORGANIZATION_ID)

    assert first.decision_id == second.decision_id


def test_different_verification_reasons_produce_different_ids():
    from app.fortress.policy_engine import evaluate_control_policy

    first_result = make_verification(
        VerificationOutcome.PASS,
        reason="First synthetic verification reason.",
    )
    second_result = make_verification(
        VerificationOutcome.PASS,
        reason="Second synthetic verification reason.",
    )

    policy = make_policy()

    first = evaluate_control_policy(first_result, policy, ORGANIZATION_ID)
    second = evaluate_control_policy(second_result, policy, ORGANIZATION_ID)

    assert first.decision_id != second.decision_id


def test_different_registry_versions_produce_different_ids():
    from app.fortress.policy_engine import evaluate_control_policy

    first_result = make_verification(
        VerificationOutcome.PASS,
        registry_version="1.0.0",
    )
    second_result = make_verification(
        VerificationOutcome.PASS,
        registry_version="1.0.0-test",
    )

    policy = make_policy()

    first = evaluate_control_policy(first_result, policy, ORGANIZATION_ID)

    with pytest.raises(PolicyEvaluationError):
        evaluate_control_policy(second_result, policy, ORGANIZATION_ID)

    assert first.decision_id.startswith("FORTRESS-")


def test_different_policy_versions_produce_different_ids():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.PASS)

    first_policy = make_policy(version="1.0.0")
    second_policy = make_policy(version="1.0.1")

    first = evaluate_control_policy(result, first_policy, ORGANIZATION_ID)
    second = evaluate_control_policy(result, second_policy, ORGANIZATION_ID)

    assert first.decision_id != second.decision_id


def test_exempt_decision_preserves_original_failure_and_risk():
    from app.fortress.policy_engine import evaluate_control_policy

    result = make_verification(VerificationOutcome.FAIL)

    decision = evaluate_control_policy(
        result,
        make_policy(),
        ORGANIZATION_ID,
        make_exception(),
    )

    assert decision.decision == PolicyDecisionOutcome.EXEMPT
    assert decision.verification_outcome == VerificationOutcome.FAIL
    assert decision.risk == RiskClassification.HIGH



