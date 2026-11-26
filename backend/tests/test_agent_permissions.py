import pytest

from app.agents.identity import AGENTS
from app.agents.permissions import (
    AgentPermission,
    FORBIDDEN_PERMISSION_NAMES,
    PERMISSION_REQUIREMENTS,
    PermissionDecision,
    evaluate_permission,
    validate_permission_contract,
)


ORG = "org-test"
TENANT = "tenant-test"


def scoped_kwargs(**overrides):
    values = {
        "organization_id": ORG,
        "tenant_id": TENANT,
        "resource_organization_id": ORG,
        "resource_tenant_id": TENANT,
    }
    values.update(overrides)
    return values


def test_permission_contract_matches_all_211_agents():
    assert len(AGENTS) == 211
    assert validate_permission_contract() is True


def test_all_agents_have_only_advisory_permission_profile():
    assert all(agent.permission_profile == "advisory_only" for agent in AGENTS)


def test_metadata_permission_is_allowed_for_registered_agents():
    for agent in AGENTS:
        result = evaluate_permission(
            agent.agent_id,
            AgentPermission.READ_AGENT_METADATA,
        )
        assert result.allowed is True
        assert isinstance(result, PermissionDecision)


def test_approved_simulation_result_read_requires_matching_scope_and_approval():
    agent_id = AGENTS[0].agent_id

    result = evaluate_permission(
        agent_id,
        AgentPermission.READ_APPROVED_SIMULATION_RESULTS,
        **scoped_kwargs(resource_is_approved=True),
    )

    assert result.allowed is True


@pytest.mark.parametrize("approval_value", [None, False, 0, "true"])
def test_simulation_result_read_denied_without_true_approval(approval_value):
    result = evaluate_permission(
        AGENTS[0].agent_id,
        AgentPermission.READ_APPROVED_SIMULATION_RESULTS,
        **scoped_kwargs(resource_is_approved=approval_value),
    )
    assert result.allowed is False


def test_advisory_proposal_allowed_with_matching_scope():
    result = evaluate_permission(
        AGENTS[0].agent_id,
        AgentPermission.SUBMIT_ADVISORY_PROPOSAL,
        **scoped_kwargs(),
    )
    assert result.allowed is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"organization_id": None},
        {"tenant_id": None},
        {"resource_organization_id": None},
        {"resource_tenant_id": None},
        {"organization_id": " "},
        {"tenant_id": ""},
    ],
)
def test_scoped_permissions_fail_closed_when_scope_is_missing(overrides):
    result = evaluate_permission(
        AGENTS[0].agent_id,
        AgentPermission.SUBMIT_ADVISORY_PROPOSAL,
        **scoped_kwargs(**overrides),
    )
    assert result.allowed is False


def test_organization_mismatch_is_denied():
    result = evaluate_permission(
        AGENTS[0].agent_id,
        AgentPermission.SUBMIT_ADVISORY_PROPOSAL,
        **scoped_kwargs(resource_organization_id="another-org"),
    )
    assert result.allowed is False
    assert "Organization scope mismatch" in result.reason


def test_tenant_mismatch_is_denied():
    result = evaluate_permission(
        AGENTS[0].agent_id,
        AgentPermission.SUBMIT_ADVISORY_PROPOSAL,
        **scoped_kwargs(resource_tenant_id="another-tenant"),
    )
    assert result.allowed is False
    assert "Tenant scope mismatch" in result.reason


@pytest.mark.parametrize("agent_id", ["", " ", None, "UNKNOWN-AGENT"])
def test_invalid_or_unknown_agent_is_denied(agent_id):
    result = evaluate_permission(
        agent_id,
        AgentPermission.READ_AGENT_METADATA,
    )
    assert result.allowed is False


@pytest.mark.parametrize(
    "permission",
    ["unknown_permission", "approve_actions", "execute_actions", None, 123],
)
def test_unknown_or_invalid_permission_is_denied(permission):
    result = evaluate_permission(AGENTS[0].agent_id, permission)
    assert result.allowed is False


@pytest.mark.parametrize("permission", sorted(FORBIDDEN_PERMISSION_NAMES))
def test_forbidden_operations_are_denied(permission):
    result = evaluate_permission(AGENTS[0].agent_id, permission)
    assert result.allowed is False


def test_capabilities_do_not_automatically_grant_permissions():
    # Only the three explicitly defined permissions are grantable.
    assert set(PERMISSION_REQUIREMENTS) == {
        "read_agent_metadata",
        "read_approved_simulation_results",
        "submit_advisory_proposal",
    }


def test_permission_requirements_are_immutable():
    with pytest.raises(TypeError):
        PERMISSION_REQUIREMENTS["new_permission"] = ("observe",)


def test_forbidden_permission_names_are_immutable():
    with pytest.raises(AttributeError):
        FORBIDDEN_PERMISSION_NAMES.add("new_operation")


def test_permission_decision_is_immutable():
    result = evaluate_permission(
        AGENTS[0].agent_id,
        AgentPermission.READ_AGENT_METADATA,
    )
    with pytest.raises((AttributeError, TypeError)):
        result.allowed = False


def test_evaluation_is_deterministic():
    args = (
        AGENTS[0].agent_id,
        AgentPermission.SUBMIT_ADVISORY_PROPOSAL,
    )
    kwargs = scoped_kwargs()

    assert evaluate_permission(*args, **kwargs) == evaluate_permission(
        *args, **kwargs
    )


def test_metadata_read_does_not_require_tenant_scope():
    result = evaluate_permission(
        AGENTS[0].agent_id,
        AgentPermission.READ_AGENT_METADATA,
    )
    assert result.allowed is True


def test_result_read_does_not_accept_approval_without_scope():
    result = evaluate_permission(
        AGENTS[0].agent_id,
        AgentPermission.READ_APPROVED_SIMULATION_RESULTS,
        resource_is_approved=True,
    )
    assert result.allowed is False
