import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from app.ai.schemas import AnalysisResult, Finding
from app.ai.service import redact_secrets
from app.models import Membership


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def register_and_login(client, email="ai-test@example.com", enable_external=True):
    response = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "StrongPassphrase123!",
        "organization_name": "AI Test Organization",
    })
    assert response.status_code == 201
    login = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "StrongPassphrase123!",
    })
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    if enable_external:
        policy = client.put(
            "/api/v1/ai/external-analysis-policy",
            headers=headers,
            json={"external_analysis_enabled": True},
        )
        assert policy.status_code == 200, policy.text
    return headers


def test_ai_endpoint_requires_authentication(client):
    response = client.post("/api/v1/ai/analyze", json={
        "analysis_type": "security_finding",
        "evidence_text": "A web server exposes an outdated TLS configuration.",
    })
    assert response.status_code == 401


def test_ai_endpoint_requires_organization_membership(client):
    headers = register_and_login(client)
    response = client.post(
        "/api/v1/ai/analyze",
        headers={**headers, "X-Organization-ID": "not-a-member"},
        json={
            "analysis_type": "security_finding",
            "evidence_text": "A web server exposes an outdated TLS configuration.",
        },
    )
    assert response.status_code == 403


def test_ai_endpoint_validates_evidence_length(client):
    headers = register_and_login(client)
    response = client.post(
        "/api/v1/ai/analyze",
        headers=headers,
        json={"analysis_type": "security_finding", "evidence_text": "too short"},
    )
    assert response.status_code == 422


def test_redact_secrets_removes_common_credentials():
    value = "api_key=AIzaSyExampleKey012345678901234 password=hunter2"
    redacted = redact_secrets(value)
    assert "AIzaSyExampleKey012345678901234" not in redacted
    assert "hunter2" not in redacted
    assert "[REDACTED]" in redacted


def test_analysis_result_requires_advisory_flags():
    result = AnalysisResult.model_validate({
        "summary": "The evidence suggests a configuration weakness.",
        "findings": [{
            "title": "Outdated TLS configuration",
            "severity": "medium",
            "explanation": "The supplied evidence indicates an outdated TLS configuration.",
            "recommendation": "Review supported TLS versions and disable obsolete protocols.",
            "confidence": "medium",
        }],
        "limitations": ["No live verification was performed."],
        "requires_human_review": True,
        "advisory_only": True,
    })
    assert result.requires_human_review is True
    assert result.advisory_only is True


# CYVANTA_AI_HTTP_ERROR_TESTS
@pytest.mark.parametrize(
    "exception_type, expected_status, expected_retry_after",
    [
        ("quota", 429, None),
        ("temporary", 503, "30"),
        ("provider", 502, None),
    ],
)
def test_ai_provider_http_error_mapping(
    client, monkeypatch, exception_type, expected_status, expected_retry_after
):
    from app.ai import service
    from app.api import ai as ai_api

    exceptions = {
        "quota": service.AIProviderQuotaExceeded,
        "temporary": service.AIProviderUnavailable,
        "provider": service.AIProviderError,
    }

    def fake_analyze(*args):
        raise exceptions[exception_type]("Private provider information")

    monkeypatch.setattr(ai_api, "analyze_with_gemini", fake_analyze)

    headers = register_and_login(client)
    response = client.post(
        "/api/v1/ai/analyze",
        headers=headers,
        json={
            "analysis_type": "security_finding",
            "evidence_text": "A test server has an unverified outdated configuration.",
        },
    )

    assert response.status_code == expected_status
    assert response.headers.get("retry-after") == expected_retry_after
    assert "Private provider information" not in response.text


def test_ai_provider_failure_does_not_bypass_authentication(client, monkeypatch):
    from app.api import ai as ai_api

    def should_not_run(*args):
        pytest.fail("Unauthenticated request must not invoke Gemini")

    monkeypatch.setattr(ai_api, "analyze_with_gemini", should_not_run)

    response = client.post(
        "/api/v1/ai/analyze",
        json={
            "analysis_type": "security_finding",
            "evidence_text": "A test server has an unverified outdated configuration.",
        },
    )

    assert response.status_code == 401

def test_ai_endpoint_blocks_external_analysis_without_org_approval(client, monkeypatch):
    from app.api import ai as ai_api

    provider_called = False

    def fake_analyze(*args):
        nonlocal provider_called
        provider_called = True
        return {
            "summary": "Test result that must not be returned.",
            "findings": [],
            "limitations": [],
            "requires_human_review": True,
            "advisory_only": True,
        }

    monkeypatch.setattr(ai_api, "analyze_with_gemini", fake_analyze)
    headers = register_and_login(client, enable_external=False)

    response = client.post(
        "/api/v1/ai/analyze",
        headers=headers,
        json={
            "analysis_type": "security_finding",
            "evidence_text": "A test server has an unverified outdated configuration.",
        },
    )

    assert response.status_code == 403
    assert provider_called is False

def test_external_analysis_policy_requires_owner_role(client):
    headers = register_and_login(client, enable_external=False)

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        membership = db.query(Membership).first()
        assert membership is not None
        membership.role = "member"
        db.commit()
    finally:
        db_generator.close()

    response = client.put(
        "/api/v1/ai/external-analysis-policy",
        headers=headers,
        json={"external_analysis_enabled": True},
    )

    assert response.status_code == 403

