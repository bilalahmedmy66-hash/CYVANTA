from dataclasses import FrozenInstanceError

import pytest

from app.fortress.registry import (
    REGISTRY_VERSION,
    LAYERS,
    CONTROLS,
    LAYERS_BY_ID,
    CONTROLS_BY_ID,
    CONTROLS_BY_LAYER,
    get_control,
    get_layer,
    get_controls_for_layer,
    validate_registry,
)


def test_registry_has_exactly_ten_layers():
    assert len(LAYERS) == 10
    assert len(LAYERS_BY_ID) == 10


def test_registry_has_exactly_one_hundred_controls():
    assert len(CONTROLS) == 100
    assert len(CONTROLS_BY_ID) == 100


def test_control_ids_are_unique():
    control_ids = [control.control_id for control in CONTROLS]
    assert len(control_ids) == len(set(control_ids))


def test_layer_ids_are_unique():
    layer_ids = [layer.layer_id for layer in LAYERS]
    assert len(layer_ids) == len(set(layer_ids))


@pytest.mark.parametrize(
    "layer",
    LAYERS,
    ids=[layer.layer_id for layer in LAYERS],
)
def test_each_layer_has_exactly_ten_controls(layer):
    controls = get_controls_for_layer(layer.layer_id)

    assert len(controls) == 10
    assert all(control.layer_id == layer.layer_id for control in controls)


@pytest.mark.parametrize(
    "layer",
    LAYERS,
    ids=[layer.layer_id for layer in LAYERS],
)
def test_controls_map_to_their_approved_vault(layer):
    controls = get_controls_for_layer(layer.layer_id)

    assert all(control.vault_id == layer.vault_id for control in controls)


def test_all_controls_have_required_metadata():
    for control in CONTROLS:
        assert control.control_id
        assert control.layer_id
        assert control.layer_name
        assert control.vault_id
        assert control.name
        assert control.description
        assert control.verification_intent
        assert control.evidence_requirements
        assert control.version == REGISTRY_VERSION
        assert control.status == "active"


def test_control_identifiers_follow_layer_prefixes():
    for layer in LAYERS:
        controls = get_controls_for_layer(layer.layer_id)

        for index, control in enumerate(controls, start=1):
            assert control.control_id == (
                f"{layer.control_prefix}-{index:03d}"
            )


def test_control_lookup_returns_expected_definition():
    first_control = CONTROLS[0]

    assert get_control(first_control.control_id) is first_control


def test_layer_lookup_returns_expected_definition():
    first_layer = LAYERS[0]

    assert get_layer(first_layer.layer_id) is first_layer


def test_unknown_control_lookup_raises_key_error():
    with pytest.raises(KeyError):
        get_control("UNKNOWN-999")


def test_unknown_layer_lookup_raises_key_error():
    with pytest.raises(KeyError):
        get_layer("unknown_layer")


def test_unknown_layer_control_list_raises_key_error():
    with pytest.raises(KeyError):
        get_controls_for_layer("unknown_layer")


def test_control_definitions_are_immutable():
    with pytest.raises(FrozenInstanceError):
        CONTROLS[0].name = "Unauthorized modification"


def test_layer_definitions_are_immutable():
    with pytest.raises(FrozenInstanceError):
        LAYERS[0].name = "Unauthorized modification"


def test_registry_lookup_mappings_are_immutable():
    with pytest.raises(TypeError):
        CONTROLS_BY_ID["INVALID-001"] = CONTROLS[0]

    with pytest.raises(TypeError):
        LAYERS_BY_ID["invalid_layer"] = LAYERS[0]

    with pytest.raises(TypeError):
        CONTROLS_BY_LAYER["invalid_layer"] = ()


def test_registry_validation_succeeds():
    assert validate_registry() is True


def test_registry_definitions_are_assurance_only():
    forbidden_fields = {
        "execute",
        "execute_action",
        "shell_command",
        "network_target",
        "remediation_action",
        "worker_dispatch",
    }

    for control in CONTROLS:
        assert not forbidden_fields.intersection(
            control.__dataclass_fields__
        )
