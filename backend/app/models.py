import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Boolean,
    JSON,
    UniqueConstraint,
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
