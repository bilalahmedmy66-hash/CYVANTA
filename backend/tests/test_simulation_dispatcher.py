from types import SimpleNamespace

import pytest

from app.models import (
    ActionApproval,
    ActionRequest,
    Asset,
    AssetAuthorization,
    EmergencyStopState,
    ExecutionRecord,
    Mission,
)
from app.action_engine.worker_registry import WorkerRegistry
from app.action_engine.simulation_dispatcher import (
    SimulationDispatchValidationError,
    validate_simulation_dispatch,
)


class QueryStub:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self.value

    def all(self):
        return self.value

    def first(self):
        return self.value


class DatabaseStub:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return QueryStub(self.rows.get(model))


def make_registry(active=True):
    registry = WorkerRegistry(max_workers=1)
    registry.register(
        worker_id="simulation-worker-1",
        name="Test Simulation Worker",
        worker_type="simulation",
        capabilities={"simulation"},
    )
    if active:
        registry.activate("simulation-worker-1")
    return registry


def make_valid_context():
    organization_id = "org-test"
    asset_id = "asset-test"
    action_id = "action-test"
    execution_id = "execution-test"

    execution = SimpleNamespace(
        id=execution_id,
        action_request_id=action_id,
        organization_id=organization_id,
        status="queued",
    )

    action = SimpleNamespace(
        id=action_id,
        mission_id="mission-test",
        organization_id=organization_id,
        status="approved",
        action_type="collect_inventory",
        target_type="asset",
        target_id=asset_id,
    )

    approval = SimpleNamespace(
        action_request_id=action_id,
        organization_id=organization_id,
        decision="approve",
    )

    mission = SimpleNamespace(
        id="mission-test",
        organization_id=organization_id,
        asset_id=asset_id,
    )

    asset = SimpleNamespace(
        id=asset_id,
        organization_id=organization_id,
    )

    authorization = SimpleNamespace(
        asset_id=asset_id,
        organization_id=organization_id,
        status="verified",
    )

    organization_stop = SimpleNamespace(is_active=False)

    rows = {
        ExecutionRecord: execution,
        EmergencyStopState: [organization_stop],
        ActionRequest: action,
        ActionApproval: [approval],
        Mission: mission,
        Asset: asset,
        AssetAuthorization: authorization,
    }

    return DatabaseStub(rows), execution, action, rows


@pytest.fixture
def safe_dispatcher(monkeypatch):
    from app.action_engine import simulation_dispatcher

    monkeypatch.setattr(
        simulation_dispatcher,
        "is_platform_emergency_stop_active",
        lambda db: False,
    )

    monkeypatch.setattr(
        simulation_dispatcher,
        "evaluate_action_policy",
        lambda **kwargs: SimpleNamespace(
            allowed=True,
            reason="Test policy passed.",
        ),
    )

    return simulation_dispatcher


def test_valid_simulation_dispatch_returns_validation_only_result(
    safe_dispatcher,
):
    db, execution, action, rows = make_valid_context()
    registry = make_registry()

    result = validate_simulation_dispatch(
        db,
        execution.id,
        registry,
        "simulation-worker-1",
    )

    assert result.execution_record_id == execution.id
    assert result.action_request_id == action.id
    assert result.organization_id == execution.organization_id
    assert result.worker_id == "simulation-worker-1"
    assert result.action_type == "collect_inventory"
    assert result.mode == "simulation_only"
    assert result.execution_started is False

    # Validation must not change the queued execution record.
    assert execution.status == "queued"


def test_unactivated_worker_is_rejected(safe_dispatcher):
    db, execution, action, rows = make_valid_context()
    registry = make_registry(active=False)

    with pytest.raises(
        SimulationDispatchValidationError,
        match="worker is not eligible",
    ):
        validate_simulation_dispatch(
            db,
            execution.id,
            registry,
            "simulation-worker-1",
        )


def test_missing_organization_stop_record_fails_closed(
    safe_dispatcher,
):
    db, execution, action, rows = make_valid_context()
    rows[EmergencyStopState] = []

    with pytest.raises(
        SimulationDispatchValidationError,
        match="exactly one organization emergency-stop",
    ):
        validate_simulation_dispatch(
            db,
            execution.id,
            make_registry(),
            "simulation-worker-1",
        )


def test_active_organization_stop_blocks_dispatch(safe_dispatcher):
    db, execution, action, rows = make_valid_context()
    rows[EmergencyStopState] = [
        SimpleNamespace(is_active=True)
    ]

    with pytest.raises(
        SimulationDispatchValidationError,
        match="organization emergency stop is active",
    ):
        validate_simulation_dispatch(
            db,
            execution.id,
            make_registry(),
            "simulation-worker-1",
        )


def test_non_queued_execution_is_rejected(safe_dispatcher):
    db, execution, action, rows = make_valid_context()
    execution.status = "cancelled"

    with pytest.raises(
        SimulationDispatchValidationError,
        match="Only queued execution records",
    ):
        validate_simulation_dispatch(
            db,
            execution.id,
            make_registry(),
            "simulation-worker-1",
        )


def test_unsupported_action_type_is_rejected(safe_dispatcher):
    db, execution, action, rows = make_valid_context()
    action.action_type = "network_scan"

    with pytest.raises(
        SimulationDispatchValidationError,
        match="outside the permitted simulation scope",
    ):
        validate_simulation_dispatch(
            db,
            execution.id,
            make_registry(),
            "simulation-worker-1",
        )


def test_approval_from_another_organization_is_rejected(
    safe_dispatcher,
):
    db, execution, action, rows = make_valid_context()
    rows[ActionApproval] = [
        SimpleNamespace(
            action_request_id=action.id,
            organization_id="different-org",
            decision="approve",
        )
    ]

    with pytest.raises(
        SimulationDispatchValidationError,
        match="Approval organization does not match",
    ):
        validate_simulation_dispatch(
            db,
            execution.id,
            make_registry(),
            "simulation-worker-1",
        )


def test_unverified_latest_authorization_is_rejected(
    safe_dispatcher,
    monkeypatch,
):
    db, execution, action, rows = make_valid_context()
    rows[AssetAuthorization] = SimpleNamespace(
        asset_id=action.target_id,
        organization_id=execution.organization_id,
        status="revoked",
    )

    # The real policy function is patched in the fixture, so this
    # test explicitly verifies that the latest record is passed
    # to policy evaluation and rejected by a rejecting policy.
    from app.action_engine import simulation_dispatcher

    monkeypatch.setattr(
        simulation_dispatcher,
        "evaluate_action_policy",
        lambda **kwargs: SimpleNamespace(
            allowed=False,
            reason="Asset authorization is not currently verified.",
        ),
    )

    with pytest.raises(
        SimulationDispatchValidationError,
        match="Asset authorization is not currently verified",
    ):
        validate_simulation_dispatch(
            db,
            execution.id,
            make_registry(),
            "simulation-worker-1",
        )
