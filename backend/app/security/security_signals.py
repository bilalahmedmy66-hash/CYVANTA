import hashlib
import hmac

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import SecuritySignal


FAILED_LOGIN_EVENT = "authentication.login_failed"


def create_account_fingerprint(
    account_identifier: str,
    hmac_key: str | None,
) -> str | None:
    """
    Create a privacy-preserving HMAC-SHA256 account fingerprint.

    A key shorter than 32 bytes is rejected.
    Raw account identifiers are never stored.
    """
    if not hmac_key or len(hmac_key.encode("utf-8")) < 32:
        return None

    normalized = account_identifier.strip().casefold()

    if not normalized:
        return None

    return hmac.new(
        hmac_key.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def record_failed_login_signal(
    db: Session,
    account_identifier: str,
    source_ip: str | None,
    hmac_key: str | None,
) -> bool:
    """
    Record a backend-generated failed-login security signal.

    If the HMAC key is unavailable, the signal is still recorded
    with a null account fingerprint.

    Database errors are rolled back and reported as False.
    """
    fingerprint = create_account_fingerprint(
        account_identifier,
        hmac_key,
    )

    try:
        db.add(
            SecuritySignal(
                event_type=FAILED_LOGIN_EVENT,
                account_fingerprint=fingerprint,
                source_ip=source_ip,
                details={
                    "signal_source": "authentication",
                },
            )
        )
        db.commit()
        return True

    except SQLAlchemyError:
        db.rollback()
        return False