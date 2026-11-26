"""Immutable logical vault definitions for CYVANTA FORTRESS V1.0.

Vaults are evidence domains within the shared CYVANTA database.
This module defines metadata and mappings only. It performs no storage,
database, network, execution, or remediation operations.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Tuple

from app.fortress.registry import (
    LAYERS,
    CONTROLS,
    REGISTRY_VERSION,
)


VAULT_MANAGER_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class VaultDefinition:
    vault_id: str
    name: str
    description: str
    evidence_domain: str
    layer_id: str
    layer_name: str
    control_ids: Tuple[str, ...]
    organization_scoped: bool
    tenant_isolation_required: bool
    shared_database: bool
    version: str
    status: str


_VAULT_METADATA = (
    (
        "identity",
        "Identity Vault",
        "Identity and authentication assurance evidence.",
        "Identity records, authentication policies, credential assurance, and session security evidence.",
    ),
    (
        "privilege",
        "Privilege Vault",
        "Authorization and privilege assurance evidence.",
        "Role catalogues, permission inventories, privilege approvals, access reviews, and authorization governance evidence.",
    ),
    (
        "tenant",
        "Tenant Vault",
        "Organizational and tenant isolation assurance evidence.",
        "Organization membership, tenant boundaries, ownership, tenant access reviews, and isolation test evidence.",
    ),
    (
        "asset",
        "Asset Vault",
        "Asset ownership and authorization assurance evidence.",
        "Asset inventories, ownership records, authorization scope, validity, approval, and lifecycle evidence.",
    ),
    (
        "platform",
        "Platform Vault",
        "Platform configuration and integrity assurance evidence.",
        "Platform configuration baselines, service inventories, hardening assessments, and configuration review evidence.",
    ),
    (
        "application",
        "Application Vault",
        "Application and API security assurance evidence.",
        "Application inventories, API policies, input validation, dependency reviews, and application security assessments.",
    ),
    (
        "data",
        "Data Vault",
        "Data protection and privacy assurance evidence.",
        "Data inventories, classification, encryption, retention, disposal, processing, and privacy review evidence.",
    ),
    (
        "threat_intelligence",
        "Threat Intelligence Vault",
        "Threat detection and security monitoring assurance evidence.",
        "Security signal inventories, detection coverage, alert policies, monitoring records, and detection validation evidence.",
    ),
    (
        "resilience",
        "Resilience Vault",
        "Operational resilience and recovery assurance evidence.",
        "Backup policies, backup integrity records, recovery objectives, recovery exercises, and continuity evidence.",
    ),
    (
        "governance",
        "Governance Vault",
        "Audit, governance, and compliance assurance evidence.",
        "Audit integrity, control ownership, policy approvals, compliance mappings, and governance review evidence.",
    ),
)


def _build_vaults() -> Tuple[VaultDefinition, ...]:
    vaults = []

    layer_by_vault = {
        layer.vault_id: layer
        for layer in LAYERS
    }

    controls_by_vault = {
        layer.vault_id: tuple(
            control.control_id
            for control in CONTROLS
            if control.vault_id == layer.vault_id
        )
        for layer in LAYERS
    }

    for vault_id, name, description, evidence_domain in _VAULT_METADATA:
        layer = layer_by_vault[vault_id]

        vaults.append(
            VaultDefinition(
                vault_id=vault_id,
                name=name,
                description=description,
                evidence_domain=evidence_domain,
                layer_id=layer.layer_id,
                layer_name=layer.name,
                control_ids=controls_by_vault[vault_id],
                organization_scoped=True,
                tenant_isolation_required=True,
                shared_database=True,
                version=VAULT_MANAGER_VERSION,
                status="active",
            )
        )

    return tuple(vaults)


VAULTS: Tuple[VaultDefinition, ...] = _build_vaults()

VAULTS_BY_ID: Mapping[str, VaultDefinition] = MappingProxyType(
    {
        vault.vault_id: vault
        for vault in VAULTS
    }
)

VAULTS_BY_LAYER: Mapping[str, VaultDefinition] = MappingProxyType(
    {
        vault.layer_id: vault
        for vault in VAULTS
    }
)

VAULTS_BY_CONTROL: Mapping[str, VaultDefinition] = MappingProxyType(
    {
        control_id: vault
        for vault in VAULTS
        for control_id in vault.control_ids
    }
)


def get_vault(vault_id: str) -> VaultDefinition:
    """Return a vault by stable ID; raise KeyError if unknown."""
    return VAULTS_BY_ID[vault_id]


def get_vault_for_layer(layer_id: str) -> VaultDefinition:
    """Return the logical vault assigned to a security layer."""
    return VAULTS_BY_LAYER[layer_id]


def get_vault_for_control(control_id: str) -> VaultDefinition:
    """Return the logical vault assigned to a control."""
    return VAULTS_BY_CONTROL[control_id]


def validate_vault_registry() -> bool:
    """Validate vault completeness, ownership boundaries, and mappings."""

    if len(VAULTS) != 10:
        raise ValueError("FORTRESS V1.0 must contain exactly 10 logical vaults.")

    if len(VAULTS_BY_ID) != 10:
        raise ValueError("Vault identifiers must be unique.")

    if len(VAULTS_BY_LAYER) != 10:
        raise ValueError("Each security layer must map to one vault.")

    if len(VAULTS_BY_CONTROL) != 100:
        raise ValueError("Every registered control must map to one vault.")

    for vault in VAULTS:
        if not vault.vault_id or not vault.name:
            raise ValueError("Vault ID and name are required.")

        if not vault.description or not vault.evidence_domain:
            raise ValueError("Vault descriptions and evidence domains are required.")

        if not vault.organization_scoped:
            raise ValueError("Vault evidence must be organization scoped.")

        if not vault.tenant_isolation_required:
            raise ValueError("Tenant isolation is mandatory for organization evidence.")

        if not vault.shared_database:
            raise ValueError("V1 vaults must use the shared CYVANTA database.")

        if vault.version != VAULT_MANAGER_VERSION:
            raise ValueError("Vault version does not match manager version.")

        if vault.status != "active":
            raise ValueError("Unexpected vault status.")

        layer = next(
            (item for item in LAYERS if item.layer_id == vault.layer_id),
            None,
        )

        if layer is None or layer.vault_id != vault.vault_id:
            raise ValueError("Vault-to-layer mapping is inconsistent.")

        expected_control_ids = tuple(
            control.control_id
            for control in CONTROLS
            if control.vault_id == vault.vault_id
        )

        if vault.control_ids != expected_control_ids:
            raise ValueError("Vault-to-control mapping is inconsistent.")

    for control in CONTROLS:
        vault = VAULTS_BY_CONTROL.get(control.control_id)

        if vault is None:
            raise ValueError(
                f"Control {control.control_id} has no logical vault."
            )

        if vault.vault_id != control.vault_id:
            raise ValueError(
                f"Control {control.control_id} maps to the wrong vault."
            )

    if REGISTRY_VERSION != "1.0.0":
        raise ValueError("Unexpected control registry version.")

    return True


validate_vault_registry()
