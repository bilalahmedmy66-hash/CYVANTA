from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import re


SUPPORTED_ACTIONS = {"collect_inventory"}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    action_id: str | None = None


def _utc(value):
    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _normalize_target(value):
    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value or "://" in value or "/" in value or ":" in value:
        return None

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass

    value = value.lower().rstrip(".")

    if not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
        value,
    ):
        return None

    return value


def evaluate_action_policy(
    action,
    asset,
    approval,
    authorization=None,
    emergency_stop=False,
):
    def deny(reason):
        return PolicyDecision(False, reason, getattr(action, "id", None))

    if emergency_stop:
        return deny("Emergency stop is active. New actions are blocked.")

    if action is None:
        return deny("Action request not found.")

    if asset is None:
        return deny("Target asset not found.")

    if approval is None:
        return deny("Action approval is required.")

    if action.status != "approved":
        return deny("Action must be approved before queueing.")

    if approval.decision != "approve":
        return deny("Action approval was not granted.")

    if action.organization_id != asset.organization_id:
        return deny("Action and asset organization do not match.")

    if action.target_id != asset.id:
        return deny("Action target does not match the supplied asset.")

    if getattr(action, "target_type", None) != "asset":
        return deny("Only explicitly supported asset targets may be queued.")

    if authorization is None:
        return deny("A verified asset authorization record is required.")

    if authorization.status != "verified":
        return deny("Asset authorization is not currently verified.")

    if authorization.organization_id != action.organization_id:
        return deny("Authorization belongs to a different organization.")

    if authorization.organization_id != asset.organization_id:
        return deny("Authorization and asset organization do not match.")

    if authorization.asset_id != asset.id:
        return deny("Authorization does not belong to this asset.")

    now = datetime.now(timezone.utc)
    valid_from = _utc(authorization.valid_from)
    expires_at = _utc(authorization.expires_at)

    if valid_from is None or expires_at is None:
        return deny("Authorization validity dates are missing or invalid.")

    if valid_from >= expires_at:
        return deny("Authorization validity period is invalid.")

    if now < valid_from:
        return deny("Authorization is not valid yet.")

    if now >= expires_at:
        return deny("Authorization has expired.")

    if not asset.assessment_enabled:
        return deny("Assessment is disabled for this asset.")

    if action.action_type not in SUPPORTED_ACTIONS:
        return deny(
            "No execution handler is registered for this action type."
        )

    scope = authorization.scope

    if not isinstance(scope, dict):
        return deny("Authorization scope is missing or malformed.")

    domains = scope.get("domains")
    ip_addresses = scope.get("ip_addresses")
    excluded_targets = scope.get("excluded_targets")
    allowed_types = scope.get("allowed_assessment_types")

    if not all(isinstance(value, list) for value in (
        domains, ip_addresses, excluded_targets, allowed_types
    )):
        return deny("Authorization scope has an invalid structure.")

    if not domains and not ip_addresses:
        return deny("Authorization scope contains no allowed targets.")

    if action.action_type not in allowed_types:
        return deny("Requested assessment type is not authorized.")

    target = _normalize_target(asset.identifier)

    if target is None:
        return deny("Asset identifier is not a supported exact domain or IP.")

    normalized_allowed = set()

    for item in domains + ip_addresses:
        normalized = _normalize_target(item)

        if normalized is None:
            return deny("Authorization contains an invalid allowed target.")

        normalized_allowed.add(normalized)

    normalized_excluded = set()

    for item in excluded_targets:
        normalized = _normalize_target(item)

        if normalized is None:
            return deny("Authorization contains an invalid excluded target.")

        normalized_excluded.add(normalized)

    if target in normalized_excluded:
        return deny("Target is explicitly excluded by authorization scope.")

    if target not in normalized_allowed:
        return deny("Target is not explicitly included in authorization scope.")

    return PolicyDecision(
        True,
        "Policy checks passed. A separate execution handler is still required.",
        action.id,
    )
