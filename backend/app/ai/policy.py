from sqlalchemy.orm import Session

from app.models import AIExternalAnalysisPolicy


def external_analysis_is_enabled(
    db: Session,
    organization_id: str,
) -> bool:
    """Fail closed unless the organization has explicitly enabled external analysis."""
    policy = (
        db.query(AIExternalAnalysisPolicy)
        .filter(
            AIExternalAnalysisPolicy.organization_id == organization_id
        )
        .first()
    )
    return bool(policy and policy.external_analysis_enabled)
