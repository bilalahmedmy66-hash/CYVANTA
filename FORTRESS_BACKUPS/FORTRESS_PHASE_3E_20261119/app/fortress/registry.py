"""Immutable CYVANTA FORTRESS V1.0 control registry.

This module contains static assurance definitions only.
It does not execute controls, contact external systems, or perform remediation.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Tuple


REGISTRY_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class LayerDefinition:
    layer_id: str
    name: str
    description: str
    vault_id: str
    control_prefix: str


@dataclass(frozen=True, slots=True)
class ControlDefinition:
    control_id: str
    layer_id: str
    layer_name: str
    vault_id: str
    name: str
    description: str
    verification_intent: str
    evidence_requirements: Tuple[str, ...]
    version: str
    status: str


_LAYER_ROWS = (
    (
        "identity_authentication",
        "Identity & Authentication Security",
        "Assures identity records, authentication policies, and session security.",
        "identity",
        "IAM",
    ),
    (
        "authorization_privilege",
        "Authorization & Privilege Security",
        "Assures role assignments, permission boundaries, and privilege governance.",
        "privilege",
        "AUTHZ",
    ),
    (
        "organizational_tenant",
        "Organizational & Tenant Security",
        "Assures organization membership integrity and tenant separation.",
        "tenant",
        "TENANT",
    ),
    (
        "asset_authorization",
        "Asset & Authorization Assurance",
        "Assures asset ownership, authorization validity, and declared scope.",
        "asset",
        "ASSET",
    ),
    (
        "platform_configuration",
        "Platform & Configuration Integrity",
        "Assures secure platform settings, configuration consistency, and hardening evidence.",
        "platform",
        "PLATFORM",
    ),
    (
        "application_api",
        "Application & API Security",
        "Assures application security configuration, API access policy, and input validation evidence.",
        "application",
        "APPSEC",
    ),
    (
        "data_protection_privacy",
        "Data Protection & Privacy",
        "Assures data classification, protection, retention, and privacy governance.",
        "data",
        "DATA",
    ),
    (
        "threat_detection_monitoring",
        "Threat Detection & Security Monitoring",
        "Assures security signal coverage, alert configuration, and monitoring evidence.",
        "threat_intelligence",
        "THREAT",
    ),
    (
        "operational_resilience",
        "Operational Resilience & Recovery",
        "Assures backup evidence, recovery readiness, and continuity planning.",
        "resilience",
        "RESILIENCE",
    ),
    (
        "audit_governance_compliance",
        "Audit, Governance & Compliance",
        "Assures audit integrity, policy ownership, compliance mapping, and control review.",
        "governance",
        "GOVERNANCE",
    ),
)

LAYERS: Tuple[LayerDefinition, ...] = tuple(
    LayerDefinition(*row) for row in _LAYER_ROWS
)


# Each row contains a control name and its specific evidence requirement.
_CONTROL_ROWS = {
    "identity_authentication": (
        ("Identity inventory", "Current identity inventory with unique subject identifiers."),
        ("Identity proofing standard", "Approved identity proofing standard and assurance criteria."),
        ("Authentication policy", "Approved authentication policy and configuration evidence."),
        ("Multi-factor authentication coverage", "MFA coverage report and documented exception register."),
        ("Credential lifecycle", "Credential issuance, rotation, expiry, and revocation records."),
        ("Password policy assurance", "Password policy settings and compliance assessment evidence."),
        ("Session lifetime policy", "Session timeout, renewal, and termination configuration records."),
        ("Session revocation assurance", "Session revocation policy and representative validation records."),
        ("Inactive identity review", "Inactive account review report and disposition records."),
        ("Authentication event accountability", "Authentication event audit samples and retention policy."),
    ),
    "authorization_privilege": (
        ("Role catalogue", "Approved role catalogue with documented responsibilities."),
        ("Permission inventory", "Current permission inventory mapped to application resources."),
        ("Role assignment governance", "Role assignment records with accountable approvers."),
        ("Least privilege review", "Periodic least-privilege review results and exceptions."),
        ("Privileged account inventory", "Inventory identifying privileged and administrative accounts."),
        ("Privilege approval evidence", "Approval records supporting privileged access assignments."),
        ("Privilege separation", "Documented separation-of-duties matrix and conflict reviews."),
        ("Privilege expiry", "Temporary privilege grants with expiry and review evidence."),
        ("Authorization policy versioning", "Versioned authorization policies and change history."),
        ("Access recertification", "Completed access recertification records and unresolved findings."),
    ),
    "organizational_tenant": (
        ("Organization inventory", "Organization records with stable identifiers and ownership."),
        ("Tenant membership integrity", "Membership records linked to valid organization records."),
        ("Membership approval", "Membership invitation, approval, and acceptance records."),
        ("Tenant context selection", "Documented tenant-context selection and validation evidence."),
        ("Tenant data ownership", "Data ownership rules identifying the responsible organization."),
        ("Tenant query isolation", "Test results demonstrating organization-scoped data access."),
        ("Cross-tenant access review", "Cross-tenant access test results and reviewed exceptions."),
        ("Organization lifecycle", "Organization activation, suspension, and closure records."),
        ("Tenant administrator accountability", "Tenant administrator assignments and review records."),
        ("Tenant isolation incident review", "Tenant isolation incident records and review outcomes."),
    ),
    "asset_authorization": (
        ("Asset inventory completeness", "Asset inventory export with identifiers and status."),
        ("Asset ownership assurance", "Ownership records linking assets to accountable organizations."),
        ("Asset classification", "Approved asset classification and criticality records."),
        ("Asset authorization scope", "Declared authorization scope and associated asset references."),
        ("Authorization validity period", "Authorization issue, effective, and expiry records."),
        ("Authorization approval integrity", "Approval history identifying reviewers and decisions."),
        ("Authorization revocation status", "Revocation and suspension records with effective timestamps."),
        ("Authorization scope consistency", "Comparison evidence between declared and approved scope."),
        ("Asset assessment eligibility", "Recorded assessment eligibility policy and status evidence."),
        ("Asset inventory reconciliation", "Reconciliation report identifying missing or conflicting assets."),
    ),
    "platform_configuration": (
        ("Platform configuration inventory", "Current platform configuration inventory."),
        ("Secure default settings", "Baseline configuration standard and measured settings."),
        ("Configuration change accountability", "Configuration change records with owner and approval."),
        ("Configuration drift review", "Configuration comparison report and reviewed deviations."),
        ("Platform service inventory", "Service inventory with purpose, owner, and lifecycle status."),
        ("Environment separation", "Documented environment boundaries and configuration evidence."),
        ("Platform dependency inventory", "Dependency inventory with versions and maintenance status."),
        ("Platform hardening assessment", "Hardening checklist and assessment results."),
        ("Platform secret handling policy", "Secret-handling standard and non-secret configuration evidence."),
        ("Platform configuration review", "Dated configuration review records and open findings."),
    ),
    "application_api": (
        ("Application inventory", "Application inventory with owners and supported versions."),
        ("API inventory", "API catalogue with documented interfaces and owners."),
        ("API authentication policy", "API authentication requirements and configuration records."),
        ("API authorization policy", "Endpoint authorization matrix and representative test results."),
        ("Input validation standard", "Input validation standard and validation test evidence."),
        ("Output handling standard", "Output encoding and response-handling requirements."),
        ("Rate limit policy", "Rate limit configuration records and documented exceptions."),
        ("API error disclosure review", "Error-response review showing sensitive detail handling."),
        ("Application dependency review", "Dependency inventory and vulnerability review records."),
        ("Application security assessment", "Application security assessment results and tracked findings."),
    ),
    "data_protection_privacy": (
        ("Data inventory", "Data inventory identifying systems, datasets, and accountable owners."),
        ("Data classification policy", "Approved data classification standard and classification records."),
        ("Sensitive data access review", "Access review records for classified and sensitive data."),
        ("Encryption at rest assurance", "Encryption policy and configuration evidence for stored data."),
        ("Encryption in transit assurance", "Transport encryption policy and configuration evidence."),
        ("Data retention schedule", "Approved retention schedule with dataset applicability."),
        ("Data disposal assurance", "Data disposal and deletion verification records."),
        ("Privacy notice governance", "Current privacy notices and documented approval history."),
        ("Data processing accountability", "Processing records identifying purpose and responsible parties."),
        ("Privacy review evidence", "Privacy assessment records, decisions, and unresolved issues."),
    ),
    "threat_detection_monitoring": (
        ("Security signal inventory", "Inventory of configured security signals and their sources."),
        ("Detection coverage mapping", "Threat coverage matrix mapped to detection capabilities."),
        ("Detection rule governance", "Versioned detection rules with owners and review history."),
        ("Alert configuration assurance", "Alert configuration records and severity definitions."),
        ("Alert routing accountability", "Alert routing policy and accountable recipient records."),
        ("Monitoring coverage", "Monitoring coverage report identifying monitored and excluded areas."),
        ("Security event retention", "Security event retention settings and policy evidence."),
        ("Detection validation records", "Documented synthetic detection test results."),
        ("Alert review accountability", "Alert review records, dispositions, and escalation evidence."),
        ("Detection gap management", "Detection gap register with owners and review status."),
    ),
    "operational_resilience": (
        ("Backup policy", "Approved backup policy defining scope and frequency."),
        ("Backup coverage inventory", "Backup coverage report mapped to critical assets and data."),
        ("Backup integrity verification", "Backup integrity check results and verification timestamps."),
        ("Backup access governance", "Backup access policy and authorized-access review records."),
        ("Recovery objectives", "Approved recovery time and recovery point objectives."),
        ("Recovery test evidence", "Dated recovery exercise results and observed outcomes."),
        ("Disaster recovery plan", "Current disaster recovery plan with owners and dependencies."),
        ("Business continuity plan", "Approved continuity plan and critical process mapping."),
        ("Resilience dependency review", "Dependency and single-point-of-failure assessment records."),
        ("Resilience corrective review", "Recovery exercise findings and tracked corrective actions."),
    ),
    "audit_governance_compliance": (
        ("Audit event inventory", "Inventory of audit event categories and recorded sources."),
        ("Audit append-only assurance", "Database or storage integrity controls and verification evidence."),
        ("Audit access governance", "Audit record access policy and access review records."),
        ("Audit retention policy", "Approved audit retention schedule and configuration evidence."),
        ("Control ownership register", "Control owner register with accountable role assignments."),
        ("Policy approval governance", "Policy approval records with version and effective date."),
        ("Policy review schedule", "Policy review calendar and completed review records."),
        ("Compliance mapping", "Control-to-requirement mapping with source references."),
        ("Control assessment history", "Dated control assessment results and reviewer attribution."),
        ("Governance exception register", "Approved governance exceptions with rationale and review dates."),
    ),
}


def _build_controls() -> Tuple[ControlDefinition, ...]:
    controls = []

    for layer in LAYERS:
        rows = _CONTROL_ROWS[layer.layer_id]

        if len(rows) != 10:
            raise ValueError(
                f"Layer {layer.layer_id} must define exactly 10 controls."
            )

        for index, (name, evidence) in enumerate(rows, start=1):
            control_id = f"{layer.control_prefix}-{index:03d}"
            controls.append(
                ControlDefinition(
                    control_id=control_id,
                    layer_id=layer.layer_id,
                    layer_name=layer.name,
                    vault_id=layer.vault_id,
                    name=name,
                    description=(
                        f"Assurance control for {name.lower()} "
                        f"within {layer.name.lower()}."
                    ),
                    verification_intent=(
                        f"Assess whether {name.lower()} is defined, "
                        "appropriately governed, current, and supported "
                        "by verifiable evidence."
                    ),
                    evidence_requirements=(
                        evidence,
                        "Evidence source, collection date, and accountable owner.",
                    ),
                    version=REGISTRY_VERSION,
                    status="active",
                )
            )

    return tuple(controls)


CONTROLS: Tuple[ControlDefinition, ...] = _build_controls()

LAYERS_BY_ID: Mapping[str, LayerDefinition] = MappingProxyType(
    {layer.layer_id: layer for layer in LAYERS}
)

CONTROLS_BY_ID: Mapping[str, ControlDefinition] = MappingProxyType(
    {control.control_id: control for control in CONTROLS}
)

CONTROLS_BY_LAYER: Mapping[str, Tuple[ControlDefinition, ...]] = MappingProxyType(
    {
        layer.layer_id: tuple(
            control for control in CONTROLS
            if control.layer_id == layer.layer_id
        )
        for layer in LAYERS
    }
)


def get_control(control_id: str) -> ControlDefinition:
    """Return a control by stable ID; raise KeyError if it is unknown."""
    return CONTROLS_BY_ID[control_id]


def get_layer(layer_id: str) -> LayerDefinition:
    """Return a layer by stable ID; raise KeyError if it is unknown."""
    return LAYERS_BY_ID[layer_id]


def get_controls_for_layer(layer_id: str) -> Tuple[ControlDefinition, ...]:
    """Return the immutable controls belonging to a layer."""
    return CONTROLS_BY_LAYER[layer_id]


def validate_registry() -> bool:
    """Validate registry completeness, uniqueness, and vault mapping."""
    if len(LAYERS) != 10:
        raise ValueError("FORTRESS V1.0 must contain exactly 10 layers.")

    if len(CONTROLS) != 100:
        raise ValueError("FORTRESS V1.0 must contain exactly 100 controls.")

    if len(LAYERS_BY_ID) != 10 or len(CONTROLS_BY_ID) != 100:
        raise ValueError("Registry identifiers must be unique.")

    for layer in LAYERS:
        layer_controls = CONTROLS_BY_LAYER[layer.layer_id]

        if len(layer_controls) != 10:
            raise ValueError(
                f"Layer {layer.layer_id} must contain exactly 10 controls."
            )

        for control in layer_controls:
            if control.layer_id != layer.layer_id:
                raise ValueError("Control layer mapping is inconsistent.")

            if control.vault_id != layer.vault_id:
                raise ValueError("Control vault mapping is inconsistent.")

            if not control.name or not control.verification_intent:
                raise ValueError("Control name and verification intent are required.")

            if not control.evidence_requirements:
                raise ValueError("Every control must specify evidence requirements.")

            if control.version != REGISTRY_VERSION:
                raise ValueError("Control version does not match registry version.")

            if control.status != "active":
                raise ValueError("Unexpected control status.")

    return True


validate_registry()
