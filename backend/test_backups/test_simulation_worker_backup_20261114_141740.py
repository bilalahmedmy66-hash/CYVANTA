import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest

from test_simulation_dispatcher_fail_closed import (
    make_test_database,
    make_registry,
    seed_valid_records,
)

from app.models import (
    ExecutionRecord,
    SimulationDispatch,
    SimulationDispatchEvent,
)

from app.action_engine.simulation_dispatcher import claim_simulation_dispatch
from app.action_engine.simulation_worker import (
    process_simulation_dispatch,
    SimulationWorkerError,
)


def create_claimed_dispatch(db, registry, seeded):
    dispatch = claim_simulation_dispatch(
        db=db,
        execution_record_id=seeded["execution_id"],
        worker_registry=registry,
        worker_id="integration-simulation-worker",
    )
    return dispatch


def test_worker_completes_with_synthetic_inventory(tmp_path):
    engine, SessionLocal = make_test_database(tmp_path)
    db = SessionLocal()

    try:
        seeded = seed_valid_records(db)
        registry = make_registry()

        dispatch = create_claimed_dispatch(db, registry, seeded)
        dispatch_id = dispatch.id
        db.close()

        db = SessionLocal()
        completed = process_simulation_dispatch(
            db=db,
            dispatch_id=dispatch_id,
            worker_registry=registry,
            worker_id="integration-simulation-worker",
        )

        assert completed.status == "completed"
        assert completed.synthetic_result["mode"] == "simulation_only"
        assert completed.synthetic_result["source"] == "synthetic_fixture"
        assert completed.synthetic_result["execution_started"] is False
        assert completed.synthetic_result["external_side_effects"] is False
        assert completed.synthetic_result["inventory"]["asset_count"] == 1

        execution = (
            db.query(ExecutionRecord)
            .filter(ExecutionRecord.id == seeded["execution_id"])
            .one()
        )
        assert execution.status == "queued"

        events = (
            db.query(SimulationDispatchEvent)
            .filter(SimulationDispatchEvent.dispatch_id == dispatch_id)
            .all()
        )
        assert len(events) == 2
        assert {event.event_type for event in events} == {
            "dispatch_claimed",
            "simulation_completed",
        }
    finally:
        db.close()
        engine.dispose()


def test_worker_rejects_wrong_worker(tmp_path):
    engine, SessionLocal = make_test_database(tmp_path)
    db = SessionLocal()

    try:
        seeded = seed_valid_records(db)
        registry = make_registry()
        dispatch = create_claimed_dispatch(db, registry, seeded)
        dispatch_id = dispatch.id
        db.close()

        db = SessionLocal()

        with pytest.raises(SimulationWorkerError):
            process_simulation_dispatch(
                db=db,
                dispatch_id=dispatch_id,
                worker_registry=registry,
                worker_id="wrong-worker",
            )

        assert db.query(SimulationDispatch).filter(
            SimulationDispatch.id == dispatch_id
        ).one().status == "claimed"

        assert db.query(ExecutionRecord).filter(
            ExecutionRecord.id == seeded["execution_id"]
        ).one().status == "queued"

        assert db.query(SimulationDispatchEvent).filter(
            SimulationDispatchEvent.dispatch_id == dispatch_id
        ).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_worker_rejects_revoked_worker(tmp_path):
    engine, SessionLocal = make_test_database(tmp_path)
    db = SessionLocal()

    try:
        seeded = seed_valid_records(db)
        registry = make_registry()
        dispatch = create_claimed_dispatch(db, registry, seeded)
        dispatch_id = dispatch.id
        registry.revoke("integration-simulation-worker")
        db.close()

        db = SessionLocal()

        with pytest.raises(SimulationWorkerError):
            process_simulation_dispatch(
                db=db,
                dispatch_id=dispatch_id,
                worker_registry=registry,
                worker_id="integration-simulation-worker",
            )

        assert db.query(SimulationDispatch).filter(
            SimulationDispatch.id == dispatch_id
        ).one().status == "claimed"

        assert db.query(ExecutionRecord).filter(
            ExecutionRecord.id == seeded["execution_id"]
        ).one().status == "queued"

        assert db.query(SimulationDispatchEvent).filter(
            SimulationDispatchEvent.dispatch_id == dispatch_id
        ).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_worker_rejects_duplicate_processing(tmp_path):
    engine, SessionLocal = make_test_database(tmp_path)
    db = SessionLocal()

    try:
        seeded = seed_valid_records(db)
        registry = make_registry()
        dispatch = create_claimed_dispatch(db, registry, seeded)
        dispatch_id = dispatch.id
        db.close()

        db = SessionLocal()
        process_simulation_dispatch(
            db=db,
            dispatch_id=dispatch_id,
            worker_registry=registry,
            worker_id="integration-simulation-worker",
        )

        db.close()
        db = SessionLocal()

        with pytest.raises(SimulationWorkerError):
            process_simulation_dispatch(
                db=db,
                dispatch_id=dispatch_id,
                worker_registry=registry,
                worker_id="integration-simulation-worker",
            )

        assert db.query(SimulationDispatchEvent).filter(
            SimulationDispatchEvent.dispatch_id == dispatch_id
        ).count() == 2
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    "scenario",
    [
        "platform_stop_missing",
        "platform_stop_active",
        "organization_stop_missing",
        "organization_stop_active",
    ],
)
def test_worker_fails_closed_when_emergency_stop_blocks(
    tmp_path,
    scenario,
):
    engine, SessionLocal = make_test_database(tmp_path)
    db = SessionLocal()

    try:
        seeded = seed_valid_records(db, scenario=scenario)
        registry = make_registry()
        dispatch = create_claimed_dispatch(db, registry, seeded)
        dispatch_id = dispatch.id
        db.close()

        db = SessionLocal()

        with pytest.raises(SimulationWorkerError):
            process_simulation_dispatch(
                db=db,
                dispatch_id=dispatch_id,
                worker_registry=registry,
                worker_id="integration-simulation-worker",
            )

        assert db.query(SimulationDispatch).filter(
            SimulationDispatch.id == dispatch_id
        ).one().status == "claimed"

        assert db.query(ExecutionRecord).filter(
            ExecutionRecord.id == seeded["execution_id"]
        ).one().status == "queued"

        assert db.query(SimulationDispatchEvent).filter(
            SimulationDispatchEvent.dispatch_id == dispatch_id
        ).count() == 1
    finally:
        db.close()
        engine.dispose()
