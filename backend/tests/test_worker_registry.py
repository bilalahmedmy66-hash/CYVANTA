import pytest

from app.action_engine.worker_capabilities import (
    CAPABILITY_SIMULATION,
    normalize_capabilities,
)
from app.action_engine.worker_registry import (
    WorkerNotEligibleError,
    WorkerRegistry,
    WorkerRegistryError,
)


def make_registry():
    return WorkerRegistry(max_workers=1)


def register_simulation_worker(registry, worker_id="simulation-worker-1"):
    return registry.register(
        worker_id=worker_id,
        name="CYVANTA Simulation Worker",
        worker_type="simulation",
        capabilities={CAPABILITY_SIMULATION},
    )


def test_registry_starts_empty_with_one_worker_capacity():
    registry = make_registry()

    assert registry.max_workers == 1
    assert registry.list_workers() == ()


def test_register_creates_worker_in_registered_state():
    registry = make_registry()

    worker = register_simulation_worker(registry)

    assert worker.worker_id == "simulation-worker-1"
    assert worker.worker_type == "simulation"
    assert worker.capabilities == frozenset({"simulation"})
    assert worker.status == "registered"
    assert worker.created_at is not None
    assert worker.updated_at is not None


def test_registration_does_not_activate_worker():
    registry = make_registry()

    worker = register_simulation_worker(registry)

    assert worker.status == "registered"
    with pytest.raises(WorkerNotEligibleError):
        registry.require_eligible(worker.worker_id)


def test_duplicate_worker_id_is_rejected():
    registry = make_registry()
    register_simulation_worker(registry)

    with pytest.raises(WorkerRegistryError, match="already registered"):
        register_simulation_worker(registry)


def test_registry_rejects_second_worker_when_capacity_is_one():
    registry = make_registry()
    register_simulation_worker(registry)

    with pytest.raises(WorkerRegistryError, match="capacity"):
        register_simulation_worker(registry, "simulation-worker-2")


def test_non_simulation_worker_type_is_rejected():
    registry = make_registry()

    with pytest.raises(ValueError, match="Only simulation"):
        registry.register(
            "worker-1",
            "Unsupported Worker",
            "security_scanner",
            {"simulation"},
        )


def test_unsupported_capability_is_rejected():
    registry = make_registry()

    with pytest.raises(ValueError, match="not permitted"):
        registry.register(
            "worker-1",
            "Unsupported Capability Worker",
            "simulation",
            {"simulation", "network_scan"},
        )


def test_missing_simulation_capability_is_rejected():
    registry = make_registry()

    with pytest.raises(ValueError, match="Simulation capability is required"):
        registry.register(
            "worker-1",
            "Worker Without Simulation",
            "simulation",
            set(),
        )


def test_capabilities_string_is_rejected():
    with pytest.raises(ValueError, match="not a string"):
        normalize_capabilities("simulation")


def test_empty_worker_identity_is_rejected():
    registry = make_registry()

    with pytest.raises(ValueError, match="worker_id"):
        registry.register("", "Worker", "simulation", {"simulation"})


def test_worker_can_be_explicitly_activated():
    registry = make_registry()
    worker = register_simulation_worker(registry)

    active = registry.activate(worker.worker_id)

    assert active.status == "active"
    assert registry.require_eligible(worker.worker_id).worker_id == worker.worker_id


def test_unknown_worker_cannot_be_activated():
    registry = make_registry()

    with pytest.raises(WorkerRegistryError, match="not registered"):
        registry.activate("missing-worker")


def test_active_worker_can_be_revoked():
    registry = make_registry()
    worker = register_simulation_worker(registry)
    registry.activate(worker.worker_id)

    revoked = registry.revoke(worker.worker_id)

    assert revoked.status == "revoked"
    with pytest.raises(WorkerNotEligibleError):
        registry.require_eligible(worker.worker_id)


def test_revoked_worker_cannot_be_reactivated():
    registry = make_registry()
    worker = register_simulation_worker(registry)
    registry.revoke(worker.worker_id)

    with pytest.raises(WorkerRegistryError, match="Only registered"):
        registry.activate(worker.worker_id)


def test_registry_returns_immutable_worker_snapshot():
    registry = make_registry()
    worker = register_simulation_worker(registry)

    snapshot = registry.list_workers()

    assert isinstance(snapshot, tuple)
    assert snapshot[0] == worker


def test_get_returns_none_for_unknown_worker():
    registry = make_registry()

    assert registry.get("missing-worker") is None


def test_registry_rejects_invalid_capacity():
    with pytest.raises(ValueError):
        WorkerRegistry(max_workers=0)

    with pytest.raises(ValueError):
        WorkerRegistry(max_workers=True)


def test_worker_id_is_normalized_before_registration():
    registry = make_registry()

    worker = register_simulation_worker(
        registry,
        worker_id="  simulation-worker-1  ",
    )

    assert worker.worker_id == "simulation-worker-1"
    assert registry.get("simulation-worker-1") == worker


def test_whitespace_variant_of_worker_id_is_rejected():
    registry = make_registry()
    register_simulation_worker(registry)

    with pytest.raises(WorkerRegistryError, match="already registered"):
        register_simulation_worker(
            registry,
            worker_id="  simulation-worker-1  ",
        )

    assert len(registry.list_workers()) == 1

def test_registry_lookup_methods_normalize_worker_ids():
    registry = make_registry()
    worker = register_simulation_worker(registry)

    assert registry.get(f"  {worker.worker_id}  ") == worker

    activated = registry.activate(f"  {worker.worker_id}  ")
    assert activated.status == "active"

    eligible = registry.require_eligible(f"  {worker.worker_id}  ")
    assert eligible.worker_id == worker.worker_id

    revoked = registry.revoke(f"  {worker.worker_id}  ")
    assert revoked.status == "revoked"


def test_registry_lookup_methods_reject_blank_ids():
    registry = make_registry()

    assert registry.get("   ") is None

    with pytest.raises(WorkerRegistryError, match="not registered"):
        registry.activate("   ")

    with pytest.raises(WorkerRegistryError, match="not registered"):
        registry.revoke("   ")

    with pytest.raises(WorkerNotEligibleError, match="not registered"):
        registry.require_eligible("   ")

def test_revocation_waits_until_eligible_worker_lease_is_released():
    from threading import Event, Thread

    registry = make_registry()
    worker = register_simulation_worker(registry)
    registry.activate(worker.worker_id)

    lease_entered = Event()
    release_lease = Event()
    revoke_finished = Event()
    errors = []

    def hold_lease():
        try:
            with registry.eligible_worker(worker.worker_id):
                lease_entered.set()
                if not release_lease.wait(timeout=5):
                    raise AssertionError("Lease release timed out.")
        except Exception as exc:
            errors.append(exc)

    def revoke_worker():
        try:
            registry.revoke(worker.worker_id)
            revoke_finished.set()
        except Exception as exc:
            errors.append(exc)

    lease_thread = Thread(target=hold_lease)
    lease_thread.start()

    assert lease_entered.wait(timeout=5), "Worker did not acquire its lease."

    revoke_thread = Thread(target=revoke_worker)
    revoke_thread.start()

    try:
        assert not revoke_finished.wait(timeout=0.2), (
            "Revocation unexpectedly completed while the lease was held."
        )
    finally:
        release_lease.set()

    lease_thread.join(timeout=5)
    revoke_thread.join(timeout=5)

    assert not lease_thread.is_alive()
    assert not revoke_thread.is_alive()
    assert not errors
    assert revoke_finished.is_set()
    assert registry.get(worker.worker_id).status == registry.STATUS_REVOKED

    with pytest.raises(WorkerNotEligibleError):
        registry.require_eligible(worker.worker_id)
