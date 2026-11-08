import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db


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


def register_and_login(client, email, organization_name):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "StrongPassphrase123!",
            "organization_name": organization_name,
        },
    )
    assert registration.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassphrase123!"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_ai_job_submission_requires_authentication(client):
    response = client.post(
        "/api/v1/ai/jobs",
        json={
            "analysis_type": "security_finding",
            "evidence_text": "A server reports an outdated TLS configuration.",
        },
    )
    assert response.status_code == 401


def test_ai_job_submission_creates_queued_job_without_exposing_evidence(client):
    headers = register_and_login(
        client, "ai-job-owner@example.com", "AI Job Organization"
    )
    response = client.post(
        "/api/v1/ai/jobs",
        headers=headers,
        json={
            "analysis_type": "security_finding",
            "evidence_text": "A server reports an outdated TLS configuration.",
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["analysis_type"] == "security_finding"
    assert payload["organization_id"]
    assert payload["submitted_by"]
    assert "evidence_text" not in payload
    assert payload["result_json"] is None


def test_ai_job_list_and_detail_are_organization_scoped(client):
    owner_headers = register_and_login(
        client, "ai-job-owner2@example.com", "Owner Organization"
    )
    other_headers = register_and_login(
        client, "ai-job-other@example.com", "Other Organization"
    )

    created = client.post(
        "/api/v1/ai/jobs",
        headers=owner_headers,
        json={
            "analysis_type": "incident_summary",
            "evidence_text": "Several failed login attempts were observed in the audit log.",
        },
    )
    assert created.status_code == 202
    job_id = created.json()["id"]

    owner_list = client.get("/api/v1/ai/jobs", headers=owner_headers)
    assert owner_list.status_code == 200
    assert [job["id"] for job in owner_list.json()["jobs"]] == [job_id]

    owner_detail = client.get(
        f"/api/v1/ai/jobs/{job_id}", headers=owner_headers
    )
    assert owner_detail.status_code == 200
    assert owner_detail.json()["id"] == job_id

    other_list = client.get("/api/v1/ai/jobs", headers=other_headers)
    assert other_list.status_code == 200
    assert other_list.json()["jobs"] == []

    other_detail = client.get(
        f"/api/v1/ai/jobs/{job_id}", headers=other_headers
    )
    assert other_detail.status_code == 404


def test_ai_job_submission_validates_evidence_length(client):
    headers = register_and_login(
        client, "ai-job-validation@example.com", "Validation Organization"
    )
    response = client.post(
        "/api/v1/ai/jobs",
        headers=headers,
        json={"analysis_type": "security_finding", "evidence_text": "too short"},
    )
    assert response.status_code == 422
def test_ai_job_retry_wait_is_exposed_safely_by_api(client):
    from datetime import timedelta
    from app.models import AIAnalysisJob, utc_now

    headers = register_and_login(
        client,
        "ai-retry-api@example.com",
        "AI Retry API Organization",
    )

    created = client.post(
        "/api/v1/ai/jobs",
        headers=headers,
        json={
            "analysis_type": "security_finding",
            "evidence_text": "A server reports an outdated TLS configuration.",
        },
    )

    assert created.status_code == 202
    job_id = created.json()["id"]

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)

    try:
        job = db.query(AIAnalysisJob).filter(
            AIAnalysisJob.id == job_id
        ).first()

        assert job is not None

        job.status = "retry_wait"
        job.attempts = 1
        job.error_code = "AI_PROVIDER_UNAVAILABLE"
        job.next_retry_at = utc_now() + timedelta(seconds=30)
        db.commit()

    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass

    response = client.get(
        f"/api/v1/ai/jobs/{job_id}",
        headers=headers,
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "retry_wait"
    assert payload["attempts"] == 1
    assert payload["error_code"] == "AI_PROVIDER_UNAVAILABLE"
    assert payload["next_retry_at"] is not None
    assert "evidence_text" not in payload