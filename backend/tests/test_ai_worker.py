from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.schemas import AnalysisResult
from app.ai.service import AIProviderUnavailable
from app.database.base import Base
from app.models import AIAnalysisJob, Organization, User, utc_now
from app.ai import worker


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    user = User(email="worker-test@example.com", password_hash="test-hash")
    organization = Organization(name="Worker Test Organization")
    session.add_all([user, organization])
    session.commit()
    session.info["user_id"] = user.id
    session.info["organization_id"] = organization.id
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def create_job(db, status="processing", evidence="A server reports an outdated TLS configuration."):
    job = AIAnalysisJob(
        organization_id=db.info["organization_id"],
        submitted_by=db.info["user_id"],
        analysis_type="security_finding",
        status=status,
        evidence_text=evidence,
        attempts=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def valid_result():
    return AnalysisResult.model_validate({
        "summary": "The supplied evidence indicates a possible TLS configuration weakness.",
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


def test_claim_next_job_claims_oldest_queued_job(db):
    first = create_job(db, status="queued")
    second = create_job(db, status="queued")

    claimed_id = worker.claim_next_job(db)

    assert claimed_id == first.id
    db.refresh(first)
    db.refresh(second)
    assert first.status == "processing"
    assert first.attempts == 1
    assert second.status == "queued"


def test_process_job_saves_advisory_result_and_clears_evidence(db, monkeypatch):
    job = create_job(db)

    def fake_analyze(analysis_type, evidence_text):
        assert analysis_type == "security_finding"
        assert "outdated TLS" in evidence_text
        return valid_result()

    monkeypatch.setattr(worker, "analyze_with_gemini", fake_analyze)
    worker.process_job(db, job.id)

    db.refresh(job)
    assert job.status == "completed"
    assert job.evidence_text is None
    assert job.result_json["advisory_only"] is True
    assert job.result_json["requires_human_review"] is True
    assert job.error_code is None
    assert job.completed_at is not None


def test_process_job_records_safe_provider_failure_and_clears_evidence(db, monkeypatch):
    job = create_job(db)

    def fake_analyze(*args):
        raise AIProviderUnavailable("private provider detail must not be stored")

    monkeypatch.setattr(worker, "analyze_with_gemini", fake_analyze)
    worker.process_job(db, job.id)

    db.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "AI_PROVIDER_UNAVAILABLE"
    assert job.evidence_text is None
    assert job.result_json is None


def test_recover_interrupted_jobs_requeues_processing_records(db):
    job = create_job(db)
    job.started_at = utc_now() - timedelta(minutes=2)
    db.commit()

    count = worker.recover_interrupted_jobs(db)

    db.refresh(job)
    assert count == 1
    assert job.status == "queued"
    assert job.started_at is None
    assert job.error_code == "WORKER_RESTART_RECOVERY"


def test_process_job_does_not_call_provider_without_evidence(db, monkeypatch):
    job = create_job(db, evidence=None)

    def should_not_run(*args):
        pytest.fail("Gemini must not be called without evidence")

    monkeypatch.setattr(worker, "analyze_with_gemini", should_not_run)
    worker.process_job(db, job.id)

    db.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "EVIDENCE_UNAVAILABLE"

def test_retry_delay_uses_bounded_backoff():
    assert worker.retry_delay(1) == 30
    assert worker.retry_delay(2) == 120
    assert worker.retry_delay(3) is None
    assert worker.retry_delay(0) is None
def test_complete_durable_retry_lifecycle(db, monkeypatch):
    test_sessions = sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    monkeypatch.setattr(worker, "SessionLocal", test_sessions)

    job = create_job(db, status="queued")

    responses = [
        AIProviderUnavailable("temporary failure one"),
        AIProviderUnavailable("temporary failure two"),
        valid_result(),
    ]

    def mocked_provider(*args):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(worker, "analyze_with_gemini", mocked_provider)

    # Attempt 1: temporary failure, schedule 30-second retry.
    assert worker.claim_next_job(db) == job.id
    worker.process_claimed_job(job.id)

    db.refresh(job)
    assert job.status == "retry_wait"
    assert job.attempts == 1
    assert job.error_code == "AI_PROVIDER_UNAVAILABLE"
    assert job.evidence_text is not None
    assert job.next_retry_at is not None

    first_deadline = job.next_retry_at

    # The job must not be claimed before its retry deadline.
    assert worker.claim_next_job(db) is None

    # Simulate the deadline passing without waiting 30 seconds.
    job.next_retry_at = utc_now() - timedelta(seconds=1)
    db.commit()

    # Attempt 2: temporary failure, schedule 120-second retry.
    assert worker.claim_next_job(db) == job.id
    worker.process_claimed_job(job.id)

    db.refresh(job)
    assert job.status == "retry_wait"
    assert job.attempts == 2
    assert job.next_retry_at is not None
    assert job.next_retry_at > first_deadline
    assert job.evidence_text is not None

    # Simulate the second deadline passing.
    job.next_retry_at = utc_now() - timedelta(seconds=1)
    db.commit()

    # Attempt 3: successful advisory analysis.
    assert worker.claim_next_job(db) == job.id
    worker.process_claimed_job(job.id)

    db.refresh(job)
    assert job.status == "completed"
    assert job.attempts == 3
    assert job.error_code is None
    assert job.evidence_text is None
    assert job.next_retry_at is None
    assert job.result_json is not None
    assert job.result_json["advisory_only"] is True
    assert job.result_json["requires_human_review"] is True

    assert responses == []
