"""Authenticated, organization-scoped advisory AI analysis endpoint."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.schemas import AnalysisRequest, AnalysisResult
from app.ai.policy import external_analysis_is_enabled
from app.ai.service import (
    AIConfigurationError,
    AIProviderError,
    AIProviderQuotaExceeded,
    AIProviderUnavailable,
    analyze_with_gemini,
)
from app.models import AIExternalAnalysisPolicy, AuditLog
from app.security.dependencies import get_current_membership
from app.database.session import get_db

router = APIRouter(prefix="/ai", tags=["AI Intelligence"])


class ExternalAnalysisPolicyUpdate(BaseModel):
    external_analysis_enabled: bool


@router.put("/external-analysis-policy")
def update_external_analysis_policy(
    data: ExternalAnalysisPolicyUpdate,
    request: Request,
    membership=Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    """Allow only the organization owner to authorize or revoke external AI analysis."""
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization owner permission required.",
        )

    policy = (
        db.query(AIExternalAnalysisPolicy)
        .filter(
            AIExternalAnalysisPolicy.organization_id
            == membership.organization_id
        )
        .first()
    )
    now = datetime.now(timezone.utc)

    if policy is None:
        policy = AIExternalAnalysisPolicy(
            organization_id=membership.organization_id,
            external_analysis_enabled=data.external_analysis_enabled,
        )
        db.add(policy)

    policy.external_analysis_enabled = data.external_analysis_enabled
    policy.approved_by = membership.user_id if data.external_analysis_enabled else None
    policy.approved_at = now if data.external_analysis_enabled else None

    db.add(
        AuditLog(
            user_id=membership.user_id,
            organization_id=membership.organization_id,
            action=(
                "ai_external_analysis_enabled"
                if data.external_analysis_enabled
                else "ai_external_analysis_disabled"
            ),
            target_type="ai_external_analysis_policy",
            target_id=membership.organization_id,
            details={
                "external_analysis_enabled": data.external_analysis_enabled,
            },
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()
    db.refresh(policy)

    return {
        "organization_id": policy.organization_id,
        "external_analysis_enabled": policy.external_analysis_enabled,
        "approved_by": policy.approved_by,
        "approved_at": policy.approved_at,
    }


@router.post("/analyze", response_model=AnalysisResult)
def analyze(
    data: AnalysisRequest,
    membership=Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    # Membership is intentionally required; the endpoint is organization-scoped.
    if not external_analysis_is_enabled(db, membership.organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="External AI analysis is disabled for this organization.",
        )

    try:
        return analyze_with_gemini(data.analysis_type, data.evidence_text)
    except AIConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI analysis is not configured on this server.",
        )
    except AIProviderQuotaExceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Gemini daily quota is exhausted. Check provider quota before retrying.",
        )
    except AIProviderUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini is temporarily busy or unavailable. Please try again shortly.",
            headers={"Retry-After": "30"},
        )
    except AIProviderError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI analysis could not be completed. Please try again later.",
        )
