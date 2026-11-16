
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import app.main as main_module

from app.database.base import Base


@pytest.fixture
def startup_client(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    monkeypatch.setattr(main_module, "engine", test_engine)

    with TestClient(main_module.app) as client:
        yield client, test_engine

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_startup_creates_platform_detection_tables(startup_client):
    _, engine = startup_client

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                """)
            ).scalars().all()
        )

    assert "platform_detection_findings" in tables
    assert "platform_detection_finding_events" in tables


def test_startup_records_platform_detection_migration(startup_client):
    _, engine = startup_client

    with engine.connect() as connection:
        version = connection.execute(
            text("""
                SELECT version
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {
                "version": (
                    "20261109_001_platform_detection_audit_immutability"
                )
            },
        ).scalar_one_or_none()

    assert version == "20261109_001_platform_detection_audit_immutability"


def test_startup_installs_platform_detection_audit_triggers(startup_client):
    _, engine = startup_client

    with engine.connect() as connection:
        triggers = set(
            connection.execute(
                text("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'trigger'
                """)
            ).scalars().all()
        )

    assert (
        "prevent_platform_detection_finding_events_update"
        in triggers
    )
    assert (
        "prevent_platform_detection_finding_events_delete"
        in triggers
    )


def test_startup_keeps_all_three_migration_versions(startup_client):
    _, engine = startup_client

    expected_versions = {
        "20261108_001_active_defense_audit_immutability",
        "20261109_001_security_signals_append_only",
        "20261109_001_platform_detection_audit_immutability",
    }

    with engine.connect() as connection:
        versions = set(
            connection.execute(
                text("""
                    SELECT version
                    FROM cyvanta_schema_migrations
                """)
            ).scalars().all()
        )

    assert expected_versions.issubset(versions)
