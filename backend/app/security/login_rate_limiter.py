
import hashlib
import hmac
import ipaddress
import math

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


WINDOW_SECONDS = 900
IP_LIMIT = 10
PAIR_LIMIT = 5


class RateLimitUnavailable(Exception):
    """Raised when login rate limiting cannot be enforced safely."""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int


def _fingerprint(
    scope: str,
    identifier: str,
    hmac_key: str,
) -> str:
    message = (
        f"cyvanta-login-rate-limit:{scope}:{identifier}"
    ).encode("utf-8")

    return hmac.new(
        hmac_key.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _utc_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)

    if not isinstance(value, datetime):
        raise TypeError("Invalid rate-limit timestamp.")

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _cleanup_expired_buckets(connection, now: datetime) -> int:
    """
    Delete rate-limit buckets whose complete window has expired.

    This runs inside the same transaction as bucket consumption.
    Active buckets are preserved.
    """
    expired_before = now - timedelta(seconds=WINDOW_SECONDS)

    result = connection.execute(
        text("""
            DELETE FROM login_rate_limits
            WHERE window_started_at <= :expired_before
        """),
        {
            "expired_before": expired_before.isoformat(sep=" "),
        },
    )

    return result.rowcount or 0


def _consume_bucket(
    connection,
    scope: str,
    fingerprint: str,
    limit: int,
    now: datetime,
):
    window_start = now - timedelta(seconds=WINDOW_SECONDS)

    result = connection.execute(
        text("""
            INSERT INTO login_rate_limits (
                scope,
                fingerprint,
                window_started_at,
                attempts
            )
            VALUES (
                :scope,
                :fingerprint,
                :now,
                1
            )
            ON CONFLICT(scope, fingerprint)
            DO UPDATE SET
                window_started_at = CASE
                    WHEN login_rate_limits.window_started_at <= :window_start
                    THEN :now
                    ELSE login_rate_limits.window_started_at
                END,
                attempts = CASE
                    WHEN login_rate_limits.window_started_at <= :window_start
                    THEN 1
                    ELSE login_rate_limits.attempts + 1
                END
            RETURNING attempts, window_started_at
        """),
        {
            "scope": scope,
            "fingerprint": fingerprint,
            "now": now.isoformat(sep=" "),
            "window_start": window_start.isoformat(sep=" "),
        },
    ).mappings().one()

    attempts = int(result["attempts"])

    stored_start = _utc_datetime(
        result["window_started_at"]
    )

    if attempts > limit:
        expires_at = stored_start + timedelta(
            seconds=WINDOW_SECONDS
        )

        remaining = max(
            1,
            math.ceil((expires_at - now).total_seconds()),
        )

        return False, remaining

    return True, 0


def consume_login_attempt(
    engine,
    ip_address: str,
    account_identifier: str,
    hmac_key: str | None,
    now: datetime | None = None,
) -> RateLimitDecision:
    """
    Atomically consume one IP bucket and one IP/account bucket.

    All login requests count, regardless of whether credentials are valid.

    Raw IP addresses and account identifiers are never persisted.

    Expired buckets are cleaned up in the same transaction.
    Storage or cleanup failures fail closed.
    """

    if not hmac_key or len(hmac_key.encode("utf-8")) < 32:
        raise RateLimitUnavailable(
            "Rate-limit HMAC key is unavailable."
        )

    if not ip_address or not account_identifier:
        raise RateLimitUnavailable(
            "Required rate-limit identity is unavailable."
        )

    try:
        normalized_ip = str(
            ipaddress.ip_address(ip_address.strip())
        )

        normalized_account = account_identifier.strip().casefold()

        if not normalized_account:
            raise ValueError("Empty account identifier.")

        current_time = _utc_datetime(
            now or datetime.now(timezone.utc)
        )

        ip_fingerprint = _fingerprint(
            "ip",
            normalized_ip,
            hmac_key,
        )

        pair_fingerprint = _fingerprint(
            "ip-account",
            f"{normalized_ip}|{normalized_account}",
            hmac_key,
        )

        with engine.begin() as connection:
            # Cleanup and both counter updates are atomic.
            _cleanup_expired_buckets(
                connection,
                current_time,
            )

            ip_allowed, ip_retry = _consume_bucket(
                connection,
                "ip",
                ip_fingerprint,
                IP_LIMIT,
                current_time,
            )

            pair_allowed, pair_retry = _consume_bucket(
                connection,
                "ip-account",
                pair_fingerprint,
                PAIR_LIMIT,
                current_time,
            )

        allowed = ip_allowed and pair_allowed

        if allowed:
            return RateLimitDecision(
                allowed=True,
                retry_after=0,
            )

        return RateLimitDecision(
            allowed=False,
            retry_after=max(ip_retry, pair_retry),
        )

    except RateLimitUnavailable:
        raise

    except Exception as exc:
        raise RateLimitUnavailable(
            "Login rate-limit enforcement failed."
        ) from exc
