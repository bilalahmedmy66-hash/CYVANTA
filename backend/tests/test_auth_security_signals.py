import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.auth as auth_module
import app.main as main_module
import app.database.session as session_module

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from app.models import SecuritySignal, User
from app.security.auth import hash_password


TEST_HMAC_KEY = "TEST_ONLY_CYVANTA_AUTH_HMAC_KEY_2026_32_BYTES_MINIMUM"


@pytest.fixture
def auth_client(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=test_engine)

    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    monkeypatch.setattr(main_module, "engine", test_engine)
    monkeypatch.setattr(session_module, "engine", test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, client=("192.0.2.10", 50000)) as client:
        yield client, TestingSessionLocal

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def register_account(client, email, password="StrongPassphrase123!"):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "organization_name": "Authentication Test Organization",
        },
    )


def get_signals(session_factory):
    with session_factory() as db:
        return db.execute(
            select(SecuritySignal)
        ).scalars().all()


def test_unknown_account_records_failed_login_signal(auth_client, monkeypatch):
    client, session_factory = auth_client
    monkeypatch.setattr(
        auth_module.settings,
        "security_event_hmac_key",
        TEST_HMAC_KEY,
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "unknown@example.com",
            "password": "WrongPassword123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

    signals = get_signals(session_factory)

    assert len(signals) == 1
    assert signals[0].event_type == "authentication.login_failed"
    assert signals[0].account_fingerprint is not None
    assert len(signals[0].account_fingerprint) == 64
    assert "unknown@example.com" not in str(signals[0].details)


def test_wrong_password_records_failed_login_signal(auth_client):
    client, session_factory = auth_client

    registration = register_account(client, "wrong-password@example.com")
    assert registration.status_code == 201

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "wrong-password@example.com",
            "password": "IncorrectPassword123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

    signals = get_signals(session_factory)

    assert len(signals) == 1
    assert signals[0].event_type == "authentication.login_failed"


def test_inactive_account_records_failed_login_signal(auth_client):
    client, session_factory = auth_client

    registration = register_account(client, "inactive@example.com")
    assert registration.status_code == 201

    with session_factory() as db:
        user = db.query(User).filter(
            User.email == "inactive@example.com"
        ).first()

        assert user is not None
        user.is_active = False
        db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "inactive@example.com",
            "password": "StrongPassphrase123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

    signals = get_signals(session_factory)

    assert len(signals) == 1
    assert signals[0].event_type == "authentication.login_failed"


def test_successful_login_does_not_record_failed_signal(auth_client):
    client, session_factory = auth_client

    registration = register_account(client, "success@example.com")
    assert registration.status_code == 201

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "success@example.com",
            "password": "StrongPassphrase123!",
        },
    )

    assert response.status_code == 200
    assert response.json()["access_token"]

    signals = get_signals(session_factory)

    assert signals == []


def test_failed_login_normalizes_email_for_signal(auth_client):
    client, session_factory = auth_client

    registration = register_account(client, "normalize@example.com")
    assert registration.status_code == 201

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "  NORMALIZE@EXAMPLE.COM  ",
            "password": "IncorrectPassword123!",
        },
    )

    assert response.status_code == 401

    signals = get_signals(session_factory)

    assert len(signals) == 1
    assert signals[0].event_type == "authentication.login_failed"




def test_login_rate_limit_returns_429_and_retry_after(auth_client, monkeypatch):
    client, _ = auth_client

    monkeypatch.setattr(
        auth_module.settings,
        "security_event_hmac_key",
        TEST_HMAC_KEY,
    )

    responses = []

    for _ in range(6):
        responses.append(
            client.post(
                "/api/v1/auth/login",
                json={
                    "email": "rate-limit@example.com",
                    "password": "WrongPassword123!",
                },
            )
        )

    assert [response.status_code for response in responses] == [
        401, 401, 401, 401, 401, 429
    ]

    blocked_response = responses[-1]

    assert blocked_response.json()["detail"] == (
        "Too many login attempts. Please try again later."
    )
    assert int(blocked_response.headers["Retry-After"]) > 0


def test_login_fails_closed_when_rate_limit_storage_is_unavailable(
    auth_client,
    monkeypatch,
):
    client, _ = auth_client

    def fail_rate_limit(**kwargs):
        raise auth_module.RateLimitUnavailable(
            "Simulated rate-limit storage failure."
        )

    def password_verification_must_not_run(*args, **kwargs):
        raise AssertionError(
            "Password verification ran despite rate-limit failure."
        )

    monkeypatch.setattr(
        auth_module,
        "consume_login_attempt",
        fail_rate_limit,
    )
    monkeypatch.setattr(
        auth_module,
        "verify_password",
        password_verification_must_not_run,
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "storage-failure@example.com",
            "password": "StrongPassphrase123!",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Authentication is temporarily unavailable."
    )
