"""Validated request/response contracts for advisory AI analysis."""
from typing import Literal

from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    analysis_type: Literal[
        "security_finding",
        "incident_summary",
        "defensive_recommendations",
    ] = "security_finding"
    evidence_text: str = Field(min_length=20, max_length=12000)


class Finding(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    severity: Literal["critical", "high", "medium", "low", "informational", "unknown"]
    explanation: str = Field(min_length=10, max_length=1200)
    recommendation: str = Field(min_length=10, max_length=1200)
    confidence: Literal["low", "medium", "high"]


class AnalysisResult(BaseModel):
    summary: str = Field(min_length=10, max_length=2000)
    findings: list[Finding] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=12)
    requires_human_review: bool = True
    advisory_only: Literal[True] = True

# CYVANTA_AI_JOB_STAGE1
from datetime import datetime
from pydantic import ConfigDict


class AIJobResponse(BaseModel):
    """Safe job metadata and advisory result; never exposes submitted evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    submitted_by: str
    analysis_type: Literal["security_finding", "incident_summary", "defensive_recommendations"]
    status: Literal["queued", "processing", "retry_wait", "completed", "failed"]
    result_json: AnalysisResult | None = None
    error_code: str | None = None
    attempts: int
    next_retry_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class AIJobListResponse(BaseModel):
    jobs: list[AIJobResponse]
