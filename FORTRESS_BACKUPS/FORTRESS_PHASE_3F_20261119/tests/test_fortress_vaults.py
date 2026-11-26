from dataclasses import FrozenInstanceError

import pytest

from app.fortress.registry import LAYERS, CONTROLS
from app.fortress.vaults import (
    VAULT_MANAGER_VERSION,
    VAULTS,
    VAULTS_BY_ID,
    VAULTS_BY_LAYER,
    VAULTS_BY_CONTROL,
    get_vault,
    get_vault_for_layer,
    get_vault_for_control,
    validate_vault_registry,
)


def test_exactly_ten_logical_vaults_exist():
    assert len(VAULTS) == 10
    assert len(VAULTS_BY_ID) == 10


def test_each_layer_maps_to_exactly_one_vault():
    assert len(VAULTS_BY_LAYER) == 10

    for layer in LAYERS:
        vault = get_vault_for_layer(layer.layer_id)
        assert vault.vault_id == layer.vault_id


def test_every_control_maps_to_exactly_one_vault():
    assert len(VAULTS_BY_CONTROL) == 100

    for control in CONTROLS:
        vault = get_vault_for_control(control.control_id)
        assert vault.vault_id == control.vault_id


@pytest.mark.parametrize(
    "vault",
    VAULTS,
    ids=[vault.vault_id for vault in VAULTS],
)
def test_each_vault_contains_ten_controls(vault):
    assert len(vault.control_ids) == 10


@pytest.mark.parametrize(
    "vault",
    VAULTS,
    ids=[vault.vault_id for vault in VAULTS],
)
def test_vaults_are_organization_scoped(vault):
    assert vault.organization_scoped is True
    assert vault.tenant_isolation_required is True


@pytest.mark.parametrize(
    "vault",
    VAULTS,
    ids=[vault.vault_id for vault in VAULTS],
)
def test_vaults_use_shared_database_boundary(vault):
    assert vault.shared_database is True


def test_vault_metadata_is_complete():
    for vault in VAULTS:
        assert vault.vault_id
        assert vault.name
        assert vault.description
        assert vault.evidence_domain
        assert vault.layer_id
        assert vault.layer_name
        assert vault.control_ids
        assert vault.version == VAULT_MANAGER_VERSION
        assert vault.status == "active"


def test_vault_ids_are_unique():
    vault_ids = [vault.vault_id for vault in VAULTS]
    assert len(vault_ids) == len(set(vault_ids))


def test_all_controls_are_accounted_for_once():
    mapped_control_ids = [
        control_id
        for vault in VAULTS
        for control_id in vault.control_ids
    ]

    assert len(mapped_control_ids) == 100
    assert len(mapped_control_ids) == len(set(mapped_control_ids))
    assert set(mapped_control_ids) == {
        control.control_id for control in CONTROLS
    }


def test_control_vault_mapping_matches_control_registry():
    for control in CONTROLS:
        vault = get_vault_for_control(control.control_id)

        assert vault.vault_id == control.vault_id
        assert vault.layer_id == control.layer_id


def test_vault_lookup_returns_expected_definition():
    first_vault = VAULTS[0]
    assert get_vault(first_vault.vault_id) is first_vault


def test_unknown_vault_lookup_raises_key_error():
    with pytest.raises(KeyError):
        get_vault("unknown_vault")


def test_unknown_layer_lookup_raises_key_error():
    with pytest.raises(KeyError):
        get_vault_for_layer("unknown_layer")


def test_unknown_control_lookup_raises_key_error():
    with pytest.raises(KeyError):
        get_vault_for_control("UNKNOWN-999")


def test_vault_definitions_are_immutable():
    with pytest.raises(FrozenInstanceError):
        VAULTS[0].name = "Unauthorized modification"


def test_vault_lookup_mappings_are_immutable():
    with pytest.raises(TypeError):
        VAULTS_BY_ID["invalid"] = VAULTS[0]

    with pytest.raises(TypeError):
        VAULTS_BY_LAYER["invalid"] = VAULTS[0]

    with pytest.raises(TypeError):
        VAULTS_BY_CONTROL["INVALID-001"] = VAULTS[0]


def test_vault_validation_succeeds():
    assert validate_vault_registry() is True
