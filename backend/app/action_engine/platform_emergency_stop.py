from sqlalchemy.exc import SQLAlchemyError

from app.models import (
    PlatformEmergencyStopEvent,
    PlatformEmergencyStopState,
    PlatformOperator,
)

PLATFORM_STOP_STATE_ID = "platform-master"


class PlatformEmergencyStopStateUnavailable(Exception):
    """Raised when the platform stop state cannot be trusted."""


class PlatformOperatorRequired(Exception):
    """Raised when an active platform operator is required."""


class InvalidPlatformStopReason(ValueError):
    """Raised when an emergency-stop change reason is invalid."""


def _clean_reason(reason):
    if not isinstance(reason, str):
        raise InvalidPlatformStopReason("A reason between 5 and 1000 characters is required.")

    cleaned = reason.strip()

    if not 5 <= len(cleaned) <= 1000:
        raise InvalidPlatformStopReason("A reason between 5 and 1000 characters is required.")

    return cleaned


def _load_singleton(db):
    """Load and validate the one permitted platform stop state."""
    rows = db.query(PlatformEmergencyStopState).all()

    if not rows:
        return None

    if len(rows) != 1 or rows[0].id != PLATFORM_STOP_STATE_ID:
        raise PlatformEmergencyStopStateUnavailable(
            "Platform emergency-stop state is malformed."
        )

    if not isinstance(rows[0].is_active, bool):
        raise PlatformEmergencyStopStateUnavailable(
            "Platform emergency-stop state is invalid."
        )

    return rows[0]


def is_platform_emergency_stop_active(db):
    """
    Return True when the platform is stopped.

    Missing, malformed, or unreadable state always fails closed.
    """
    try:
        state = _load_singleton(db)

        # No state means the platform has not been explicitly released.
        if state is None:
            return True

        return state.is_active

    except PlatformEmergencyStopStateUnavailable:
        db.rollback()
        raise

    except SQLAlchemyError as exc:
        db.rollback()
        raise PlatformEmergencyStopStateUnavailable(
            "Platform emergency-stop state could not be verified."
        ) from exc


def set_platform_emergency_stop(db, operator_id, is_active, reason):
    """
    Change the platform-wide emergency stop.

    Only an active platform operator can change it.
    State transition and immutable audit event are committed together.
    """
    if not isinstance(is_active, bool):
        raise ValueError("is_active must be a boolean.")

    cleaned_reason = _clean_reason(reason)

    try:
        # Serialize SQLite writers before checking authorization and state.
        connection = db.connection()

        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")

        operator = (
            db.query(PlatformOperator)
            .filter(
                PlatformOperator.id == operator_id,
                PlatformOperator.is_active.is_(True),
            )
            .one_or_none()
        )

        if operator is None:
            raise PlatformOperatorRequired(
                "An active platform operator is required."
            )

        state = _load_singleton(db)

        if state is None:
            state = PlatformEmergencyStopState(
                id=PLATFORM_STOP_STATE_ID,
                is_active=is_active,
                reason=cleaned_reason,
                changed_by_operator_id=operator.id,
            )
            db.add(state)
        else:
            state.is_active = is_active
            state.reason = cleaned_reason
            state.changed_by_operator_id = operator.id

        event = PlatformEmergencyStopEvent(
            event_type="activated" if is_active else "deactivated",
            operator_id=operator.id,
            reason=cleaned_reason,
            details={"state_id": PLATFORM_STOP_STATE_ID},
        )
        db.add(event)

        db.flush()
        db.commit()
        db.refresh(state)

        return state

    except (PlatformOperatorRequired, PlatformEmergencyStopStateUnavailable, InvalidPlatformStopReason, ValueError):
        db.rollback()
        raise

    except SQLAlchemyError as exc:
        db.rollback()
        raise PlatformEmergencyStopStateUnavailable(
            "Platform emergency-stop change could not be completed."
        ) from exc

    except Exception:
        db.rollback()
        raise
