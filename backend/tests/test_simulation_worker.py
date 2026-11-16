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
    Asset,
    ActionRequest,
    ActionApproval,
    AssetAuthorization,
    ExecutionRecord,
    SimulationDispatch,
    SimulationDispatchEvent,
)

from app.action_engine.simulation_dispatcher import claim_simulation_dispatch
from app.action_engine.simulation_worker import (
    process_simulation_dispatch,
    SimulationWorkerError,
)


def snapshot_protected_records(db, execution_id):
    execution = (
        db.query(ExecutionRecord)
        .filter(ExecutionRecord.id == execution_id)
        .one()
    )
    action = db.get(ActionRequest, execution.action_request_id)
    assert action is not None

    asset = db.get(Asset, action.target_id)
    assert asset is not None

    approval = (
        db.query(ActionApproval)
        .filter(ActionApproval.action_request_id == action.id)
        .one()
    )

    authorization = (
        db.query(AssetAuthorization)
        .filter(
            AssetAuthorization.asset_id == asset.id,
            AssetAuthorization.organization_id == asset.organization_id,
        )
        .one()
    )

    records = {
        "asset": asset,
        "action_request": action,
        "approval": approval,
        "authorization": authorization,
    }

    return {
        name: {
            column.name: getattr(record, column.name)
            for column in record.__table__.columns
        }
        for name, record in records.items()
    }


def create_claimed_dispatch(db, registry, seeded):
    # Seeding is committed; ensure the session is clean.
    db.rollback()

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
        protected_before = snapshot_protected_records(
            db, seeded["execution_id"]
        )

        # Snapshot query opened a transaction; use a clean session.
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

        db.expire_all()
        protected_after = snapshot_protected_records(
            db, seeded["execution_id"]
        )
        assert protected_after == protected_before

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
        # Always claim while both emergency stops are inactive.
        seeded = seed_valid_records(db)
        registry = make_registry()

        dispatch = create_claimed_dispatch(db, registry, seeded)
        dispatch_id = dispatch.id

        # Change the relevant stop state only after the claim.
        db.rollback()

        if scenario == "platform_stop_missing":
            from app.models import PlatformEmergencyStopState

            db.query(PlatformEmergencyStopState).delete()
            db.commit()

        elif scenario == "platform_stop_active":
            from app.models import PlatformEmergencyStopState

            state = db.query(PlatformEmergencyStopState).one()
            state.is_active = True
            db.commit()

        elif scenario == "organization_stop_missing":
            from app.models import EmergencyStopState

            organization_state = (
                db.query(EmergencyStopState)
                .filter(
                    EmergencyStopState.organization_id
                    == dispatch.organization_id
                )
                .one()
            )
            db.delete(organization_state)
            db.commit()

        elif scenario == "organization_stop_active":
            from app.models import EmergencyStopState

            organization_state = (
                db.query(EmergencyStopState)
                .filter(
                    EmergencyStopState.organization_id
                    == dispatch.organization_id
                )
                .one()
            )
            organization_state.is_active = True
            db.commit()

        db.close()
        db = SessionLocal()

        with pytest.raises(SimulationWorkerError):
            process_simulation_dispatch(
                db=db,
                dispatch_id=dispatch_id,
                worker_registry=registry,
                worker_id="integration-simulation-worker",
            )

        dispatch_after = (
            db.query(SimulationDispatch)
            .filter(SimulationDispatch.id == dispatch_id)
            .one()
        )
        assert dispatch_after.status == "claimed"

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
        assert len(events) == 1
        assert events[0].event_type == "dispatch_claimed"

    finally:
        db.close()
        engine.dispose()






@pytest.mark.parametrize(
    "scenario",
    [
        "approval_rejected_after_claim",
        "authorization_revoked_after_claim",
    ],
)
def test_worker_rejects_stale_approval_or_authorization(
    tmp_path,
    scenario,
):
    engine, SessionLocal = make_test_database(tmp_path)
    db = SessionLocal()

    try:
        seeded = seed_valid_records(db)
        registry = make_registry()

        dispatch = create_claimed_dispatch(db, registry, seeded)
        dispatch_id = dispatch.id

        # The dispatch was valid when claimed. Change authorization afterward.
        db.rollback()

        execution = (
            db.query(ExecutionRecord)
            .filter(ExecutionRecord.id == seeded["execution_id"])
            .one()
        )

        action = db.get(ActionRequest, execution.action_request_id)
        assert action is not None

        if scenario == "approval_rejected_after_claim":
            approval = (
                db.query(ActionApproval)
                .filter(ActionApproval.action_request_id == action.id)
                .one()
            )
            approval.decision = "reject"

        elif scenario == "authorization_revoked_after_claim":
            authorization = (
                db.query(AssetAuthorization)
                .filter(
                    AssetAuthorization.asset_id == action.target_id,
                    AssetAuthorization.organization_id
                    == action.organization_id,
                )
                .one()
            )
            authorization.status = "revoked"

        db.commit()
        db.close()
        db = SessionLocal()

        # Fresh validation must reject the previously claimed dispatch.
        with pytest.raises(SimulationWorkerError):
            process_simulation_dispatch(
                db=db,
                dispatch_id=dispatch_id,
                worker_registry=registry,
                worker_id="integration-simulation-worker",
            )

        dispatch_after = (
            db.query(SimulationDispatch)
            .filter(SimulationDispatch.id == dispatch_id)
            .one()
        )
        assert dispatch_after.status == "claimed"

        execution_after = (
            db.query(ExecutionRecord)
            .filter(ExecutionRecord.id == seeded["execution_id"])
            .one()
        )
        assert execution_after.status == "queued"

        events = (
            db.query(SimulationDispatchEvent)
            .filter(SimulationDispatchEvent.dispatch_id == dispatch_id)
            .all()
        )
        assert len(events) == 1
        assert events[0].event_type == "dispatch_claimed"

    finally:
        db.close()
        engine.dispose()
