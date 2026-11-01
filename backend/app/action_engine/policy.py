from dataclasses import dataclass


SUPPORTED_ACTIONS = {
    "collect_inventory",
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    action_id: str | None = None


def evaluate_action_policy(
    action,
    asset,
    approval,
    emergency_stop: bool = False,
) -> PolicyDecision:

    if emergency_stop:
        return PolicyDecision(
            False,
            "Emergency stop is active.",
            getattr(action, "id", None),
        )

    if action is None:
        return PolicyDecision(False, "Action request does not exist.")

    if asset is None:
        return PolicyDecision(
            False,
            "Target asset does not exist.",
            action.id,
        )

    if approval is None:
        return PolicyDecision(
            False,
            "An approval record is required.",
            action.id,
        )

    if action.status != "approved":
        return PolicyDecision(
            False,
            "Action is not approved.",
            action.id,
        )

    if approval.decision != "approve":
        return PolicyDecision(
            False,
            "Approval decision is not affirmative.",
            action.id,
        )

    if action.organization_id != asset.organization_id:
        return PolicyDecision(
            False,
            "Action and asset organization do not match.",
            action.id,
        )

    if action.target_id != asset.id:
        return PolicyDecision(
            False,
            "Action target does not match the supplied asset.",
            action.id,
        )

    if asset.authorization_status != "verified":
        return PolicyDecision(
            False,
            "Asset authorization has not been independently verified.",
            action.id,
        )

    if not asset.assessment_enabled:
        return PolicyDecision(
            False,
            "Security assessment is not enabled for this asset.",
            action.id,
        )

    if action.action_type not in SUPPORTED_ACTIONS:
        return PolicyDecision(
            False,
            "No approved execution handler exists for this action type.",
            action.id,
        )

    return PolicyDecision(
        True,
        "Policy checks passed. A separate execution handler is still required.",
        action.id,
    )
