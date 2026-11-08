"""Authenticated, organization-scoped advisory AI analysis endpoint."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.schemas import AnalysisRequest, AnalysisResult
from app.ai.service import (
    AIConfigurationError,
    AIProviderError,
    AIProviderUnavailable,
    analyze_with_gemini,
)
from app.security.dependencies import get_current_membership

router = APIRouter(prefix="/ai", tags=["AI Intelligence"])


@router.post("/analyze", response_model=AnalysisResult)
def analyze(
    data: AnalysisRequest,
    membership=Depends(get_current_membership),
):
    # Membership is intentionally required; the endpoint is organization-scoped.
    _ = membership.organization_id

    try:
        return analyze_with_gemini(data.analysis_type, data.evidence_text)
    except AIConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI analysis is not configured on this server.",
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
