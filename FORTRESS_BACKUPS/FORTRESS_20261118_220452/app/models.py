import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Boolean,
    JSON,
    UniqueConstraint,
    CheckConstraint,
    Integer,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def generate_id():
    return str(uuid.uuid4())


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Membership(Base):
    __tablename__ = "memberships"

    __table_args__ = (
        UniqueConstraint(
            "user_id", "organization_id",
            name="uq_user_organization"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(30), default="member", nullable=False
    )



class OrganizationInvitation(Base):
    __tablename__ = "organization_invitations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="reviewer")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    identifier: Mapped[str] = mapped_column(String(500), nullable=False)

    authorization_reference: Mapped[str] = mapped_column(
        String(500), nullable=False
    )
    authorization_status: Mapped[str] = mapped_column(
        String(30), default="declared", nullable=False
    )
    assessment_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

# ==========================================
# CYVANTA MISSION CONTROLLER MODELS
# ==========================================

from sqlalchemy import Integer, Text


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )

    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id"), nullable=True
    )

    title: Mapped[str] = mapped_column(
        String(200), nullable=False
    )

    objective: Mapped[str] = mapped_column(
        Text, nullable=False
    )

    priority: Mapped[str] = mapped_column(
        String(20), default="normal", nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30), default="planned", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MissionTask(Base):
    __tablename__ = "mission_tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(
        String(200), nullable=False
    )

    description: Mapped[str] = mapped_column(
        Text, nullable=False
    )

    assigned_agent: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False
    )

    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ActionRequest(Base):
    __tablename__ = "action_requests"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id"), nullable=False, index=True
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )

    requested_by: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    action_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    target_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )

    target_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )

    description: Mapped[str] = mapped_column(
        Text, nullable=False
    )

    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30), default="pending_approval", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ActionApproval(Base):
    __tablename__ = "action_approvals"

    __table_args__ = (
        UniqueConstraint(
            "action_request_id",
            name="uq_action_approval",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    action_request_id: Mapped[str] = mapped_column(
        ForeignKey("action_requests.id"), nullable=False
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )

    decided_by: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    decision: Mapped[str] = mapped_column(
        String(20), nullable=False
    )

    reason: Mapped[str] = mapped_column(
        Text, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ExecutionRecord(Base):
    __tablename__ = "execution_records"

    __table_args__ = (
        UniqueConstraint(
            "action_request_id",
            name="uq_execution_action_request",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    action_request_id: Mapped[str] = mapped_column(
        ForeignKey("action_requests.id"), nullable=False, index=True
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30), default="queued", nullable=False
    )

    result: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )

    verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


# ==========================================
# CYVANTA SIMULATION DISPATCH MODELS
# ==========================================

class SimulationDispatch(Base):
    """
    Tracks simulation-only dispatches separately from execution records.
    This model does not represent real security-operation execution.
    """

    __tablename__ = "simulation_dispatches"

    __table_args__ = (
        UniqueConstraint(
            "execution_record_id",
            name="uq_simulation_dispatch_execution_record",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'completed', 'failed', 'cancelled')",
            name="ck_simulation_dispatch_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    execution_record_id: Mapped[str] = mapped_column(
        ForeignKey("execution_records.id"),
        nullable=False,
        index=True,
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", index=True
    )

    worker_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    synthetic_result: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class SimulationDispatchEvent(Base):
    """
    Append-only history of simulation dispatch events.
    """

    __tablename__ = "simulation_dispatch_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    dispatch_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_dispatches.id"),
        nullable=False,
        index=True,
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )

    worker_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    details: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


# ==========================================
# CYVANTA EMERGENCY STOP MODEL
# ==========================================

class EmergencyStopState(Base):
    __tablename__ = "emergency_stop_states"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"),
        unique=True,
        nullable=False,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    changed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

class AssetAuthorization(Base):
    """
    Historical authorization record for one organization asset.

    An authorization request does not grant permission by itself.
    Assessment access requires a separately approved, currently valid
    authorization and a matching explicit scope.
    """

    __tablename__ = "asset_authorizations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        nullable=False,
        index=True,
    )

    submitted_by: Mapped[str] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    evidence_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    evidence_reference: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )

    scope: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    decision_reason: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspended_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspension_reason: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    revoked_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class AuthorizationLifecycleEvent(Base):
    """
    Append-only history of authorization lifecycle transitions.

    Application endpoints may insert events but must not update or delete
    historical lifecycle records.
    """

    __tablename__ = "authorization_lifecycle_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    authorization_id: Mapped[str] = mapped_column(
        ForeignKey("asset_authorizations.id"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    actor_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )

    details: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )


class ExecutionLifecycleEvent(Base):
    """
    Append-only history of execution state transitions.
    """

    __tablename__ = "execution_lifecycle_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    execution_id: Mapped[str] = mapped_column(
        ForeignKey("execution_records.id"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    from_status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    to_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    details: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

# CYVANTA_AI_JOB_STAGE1
from sqlalchemy import Text


class AIAnalysisJob(Base):
    """Organization-scoped, advisory-only AI analysis work item."""

    __tablename__ = "ai_analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

# CYVANTA_ACTIVE_DEFENSE_MODELS_V1
# Foundational, organization-scoped Active Defense data models.
# This phase adds storage only. It does not enable detection or containment.

class ThreatEvent(Base):
    __tablename__ = "threat_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open", index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ThreatEventLifecycleEvent(Base):
    __tablename__ = "threat_event_lifecycle_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    threat_event_id: Mapped[str] = mapped_column(ForeignKey("threat_events.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class DefensePolicy(Base):
    __tablename__ = "defense_policies"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_defense_policy_organization"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="alert-only")
    enabled_rules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    severity_threshold: Mapped[str] = mapped_column(String(20), nullable=False, default="high")
    auto_containment_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ContainmentAction(Base):
    __tablename__ = "containment_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    threat_event_id: Mapped[str | None] = mapped_column(ForeignKey("threat_events.id"), nullable=True, index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContainmentActionEvent(Base):
    __tablename__ = "containment_action_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    containment_action_id: Mapped[str] = mapped_column(ForeignKey("containment_actions.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class Alert(Base):
    __tablename__ = "defense_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    threat_event_id: Mapped[str | None] = mapped_column(ForeignKey("threat_events.id"), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="unread", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class AlertDeliveryEvent(Base):
    __tablename__ = "alert_delivery_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("defense_alerts.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    destination_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class PlatformEmergencyStopState(Base):
    __tablename__ = "platform_emergency_stop_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    changed_by_operator_id: Mapped[str | None] = mapped_column(ForeignKey("platform_operators.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class PlatformEmergencyStopEvent(Base):
    __tablename__ = "platform_emergency_stop_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    operator_id: Mapped[str | None] = mapped_column(ForeignKey("platform_operators.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class PlatformOperator(Base):
    __tablename__ = "platform_operators"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    granted_by_operator_id: Mapped[str | None] = mapped_column(ForeignKey("platform_operators.id"), nullable=True)
    grant_reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformOperatorEvent(Base):
    __tablename__ = "platform_operator_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    operator_id: Mapped[str] = mapped_column(ForeignKey("platform_operators.id"), nullable=False, index=True)
    target_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    actor_operator_id: Mapped[str | None] = mapped_column(ForeignKey("platform_operators.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class SecuritySession(Base):
    __tablename__ = "security_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_id_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
# ==========================================
# CYVANTA TRUSTED SECURITY SIGNALS
# ==========================================

class SecuritySignal(Base):
    __tablename__ = "security_signals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    account_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    source_ip: Mapped[str | None] = mapped_column(
        String(45), nullable=True, index=True
    )
    details: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now,
        nullable=False, index=True
    )

# ==========================================
# CYVANTA PLATFORM DETECTION FINDINGS
# ==========================================

class PlatformDetectionFinding(Base):
    __tablename__ = "platform_detection_findings"
    __table_args__ = (
        UniqueConstraint(
            "deduplication_key",
            name="uq_platform_detection_finding_deduplication_key",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )
    rule_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    deduplication_key: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="open", index=True
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    evidence: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    occurrence_count: Mapped[int] = mapped_column(
        default=1, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now,
        onupdate=utc_now, nullable=False
    )


class PlatformDetectionFindingEvent(Base):
    __tablename__ = "platform_detection_finding_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_id
    )
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("platform_detection_findings.id"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(
        String(1000), nullable=False, default=""
    )
    details: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now,
        nullable=False, index=True
    )

class LoginRateLimit(Base):
    """
    Mutable authentication rate-limit buckets.
    Stores HMAC fingerprints, never raw IPs or account identifiers.
    """

    __tablename__ = "login_rate_limits"

    __table_args__ = (
        CheckConstraint(
            "attempts > 0",
            name="ck_login_rate_limits_attempts_positive",
        ),
    )

    scope: Mapped[str] = mapped_column(
        String(30),
        primary_key=True,
    )

    fingerprint: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

