from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.action_engine.emergency_stop import (
    EmergencyStopStateUnavailable,
    is_emergency_stop_active,
)


class FailingQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        raise SQLAlchemyError("Simulated database failure")


class FailingDatabase:
    def __init__(self):
        self.rollback_called = False

    def query(self, model):
        return FailingQuery()

    def rollback(self):
        self.rollback_called = True


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result


class FakeDatabase:
    def __init__(self, result):
        self.result = result

    def query(self, model):
        return FakeQuery(self.result)


def test_database_error_raises_unavailable_exception():
    db = FailingDatabase()

    with pytest.raises(EmergencyStopStateUnavailable):
        is_emergency_stop_active(db, "organization-001")


def test_database_error_rolls_back_session():
    db = FailingDatabase()

    with pytest.raises(EmergencyStopStateUnavailable):
        is_emergency_stop_active(db, "organization-001")

    assert db.rollback_called is True


def test_missing_state_is_inactive():
    db = FakeDatabase(None)

    result = is_emergency_stop_active(db, "organization-001")

    assert result is False


def test_saved_active_state_returns_true():
    state = SimpleNamespace(is_active=True)
    db = FakeDatabase(state)

    result = is_emergency_stop_active(db, "organization-001")

    assert result is True
