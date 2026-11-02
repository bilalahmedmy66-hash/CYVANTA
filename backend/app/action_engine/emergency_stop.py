from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import EmergencyStopState


class EmergencyStopStateUnavailable(Exception):
    """Raised when the Emergency Stop state cannot be safely read."""


def is_emergency_stop_active(
    db: Session,
    organization_id: str,
) -> bool:
    """
    Read the persistent Emergency Stop state for one organization.

    A missing state means the organization has not activated the stop.
    Database errors fail closed by raising EmergencyStopStateUnavailable.
    """

    try:
        state = (
            db.query(EmergencyStopState)
            .filter(
                EmergencyStopState.organization_id == organization_id
            )
            .first()
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise EmergencyStopStateUnavailable(
            "Emergency Stop state could not be verified."
        ) from exc

    return bool(state and state.is_active)
