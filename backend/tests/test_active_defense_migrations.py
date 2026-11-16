import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database.base import Base
from app import models  # noqa: F401
from app.database.migrations import (
    ACTIVE_DEFENSE_APPEND_ONLY_TABLES,
    ACTIVE_DEFENSE_MIGRATION_VERSION,
    ensure_active_defense_migrations,
)


@pytest.fixture
def migration_engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_active_defense_migration_is_idempotent(migration_engine):
    ensure_active_defense_migrations(migration_engine)
    ensure_active_defense_migrations(migration_engine)

    with migration_engine.connect() as connection:
        versions = connection.execute(
            text("SELECT version FROM cyvanta_schema_migrations")
        ).scalars().all()

    assert versions == [ACTIVE_DEFENSE_MIGRATION_VERSION]


def test_append_only_triggers_exist(migration_engine):
    ensure_active_defense_migrations(migration_engine)

    with migration_engine.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            ).all()
        }

    for table in ACTIVE_DEFENSE_APPEND_ONLY_TABLES:
        assert f"prevent_{table}_update" in names
        assert f"prevent_{table}_delete" in names


@pytest.mark.parametrize(
    ("model", "kwargs", "row_id"),
    [
        (
            models.ThreatEventLifecycleEvent,
            {
                "organization_id": "org-test",
                "threat_event_id": "threat-test",
                "event_type": "created",
                "reason": "test record",
            },
            "audit-test-1",
        ),
        (
            models.ContainmentActionEvent,
            {
                "organization_id": "org-test",
                "containment_action_id": "action-test",
                "event_type": "requested",
                "reason": "test record",
            },
            "audit-test-2",
        ),
        (
            models.AlertDeliveryEvent,
            {
                "organization_id": "org-test",
                "alert_id": "alert-test",
                "channel": "in_app",
                "status": "sent",
            },
            "audit-test-3",
        ),
        (
            models.PlatformEmergencyStopEvent,
            {
                "event_type": "activated",
                "reason": "test record",
            },
            "audit-test-4",
        ),
        (
            models.PlatformOperatorEvent,
            {
                "operator_id": "operator-test",
                "target_user_id": "user-test",
                "event_type": "granted",
                "reason": "test record",
            },
            "audit-test-5",
        ),
        (
            models.AuthorizationLifecycleEvent,
            {
                "organization_id": "org-test",
                "authorization_id": "authorization-test",
                "event_type": "created",
                "actor_id": "actor-test",
                "reason": "test record",
            },
            "audit-test-6",
        ),
        (
            models.ExecutionLifecycleEvent,
            {
                "organization_id": "org-test",
                "execution_id": "execution-test",
                "event_type": "queued",
                "to_status": "queued",
            },
            "audit-test-7",
        ),
    ],
)
def test_append_only_tables_reject_update_and_delete(
    migration_engine, model, kwargs, row_id
):
    ensure_active_defense_migrations(migration_engine)

    # ORM insertion applies UUID/timestamp/JSON defaults declared by the models.
    with Session(migration_engine) as session:
        record = model(id=row_id, **kwargs)
        session.add(record)
        session.commit()

    table_name = model.__tablename__

    with pytest.raises(DBAPIError, match="append-only audit history"):
        with migration_engine.begin() as connection:
            connection.execute(
                text(f"UPDATE {table_name} SET id = id WHERE id = :row_id"),
                {"row_id": row_id},
            )

    with pytest.raises(DBAPIError, match="append-only audit history"):
        with migration_engine.begin() as connection:
            connection.execute(
                text(f"DELETE FROM {table_name} WHERE id = :row_id"),
                {"row_id": row_id},
            )


def test_migration_preserves_existing_tables(migration_engine):
    before = set(inspect(migration_engine).get_table_names())
    ensure_active_defense_migrations(migration_engine)
    after = set(inspect(migration_engine).get_table_names())

    assert before.issubset(after)
    assert {"users", "organizations", "assets"}.issubset(after)
