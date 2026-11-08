"""Organization-scoped API for submitting and tracking advisory AI jobs."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.ai.schemas import AIJobListResponse, AIJobResponse, AnalysisRequest
from app.ai.service import redact_secrets
from app.database.session import get_db
from app.models import AIAnalysisJob
from app.security.dependencies import get_current_membership

router = APIRouter(prefix="/ai/jobs", tags=["AI Intelligence Jobs"])


@router.post("", response_model=AIJobResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_ai_job(
    data: AnalysisRequest,
    membership=Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    """Create a queued advisory job; processing is handled by a separate worker."""
    job = AIAnalysisJob(
        organization_id=membership.organization_id,
        submitted_by=membership.user_id,
        analysis_type=data.analysis_type,
        evidence_text=redact_secrets(data.evidence_text),
        status="queued",
        attempts=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=AIJobListResponse)
def list_ai_jobs(
    membership=Depends(get_current_membership),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
):
    """List jobs visible to the active organization, newest first."""
    jobs = (
        db.query(AIAnalysisJob)
        .filter(AIAnalysisJob.organization_id == membership.organization_id)
        .order_by(AIAnalysisJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"jobs": jobs}


@router.get("/{job_id}", response_model=AIJobResponse)
def get_ai_job(
    job_id: str,
    membership=Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    """Retrieve one job only if it belongs to the active organization."""
    job = (
        db.query(AIAnalysisJob)
        .filter(
            AIAnalysisJob.id == job_id,
            AIAnalysisJob.organization_id == membership.organization_id,
        )
        .first()
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI analysis job was not found.",
        )
    return job