from typing import Literal
from datetime import datetime, timezone
import ipaddress
import re

from pydantic import (
    BaseModel, ConfigDict, EmailStr, Field,
    field_validator, model_validator,
)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    organization_name: str = Field(min_length=2, max_length=150)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RegistrationResponse(BaseModel):
    user: UserResponse
    organization_id: str
    organization_name: str


class OrganizationInvitationCreateRequest(BaseModel):
    email: EmailStr
    role: Literal["reviewer"] = "reviewer"


class OrganizationInvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class OrganizationInvitationResponse(BaseModel):
    id: str
    organization_id: str
    email: EmailStr
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class OrganizationMemberResponse(BaseModel):
    user_id: str
    email: EmailStr
    role: str

class AssetCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    asset_type: Literal["computer", "server", "website", "network", "cloud"]
    identifier: str = Field(min_length=1, max_length=500)
    authorization_reference: str = Field(min_length=3, max_length=500)
    authorization_confirmed: bool


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    asset_type: str
    identifier: str
    authorization_reference: str
    authorization_status: str
    assessment_enabled: bool


class MessageResponse(BaseModel):
    message: str

class AuthorizationScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domains: list[str] = Field(default_factory=list, max_length=100)
    ip_addresses: list[str] = Field(default_factory=list, max_length=100)
    excluded_targets: list[str] = Field(default_factory=list, max_length=100)

    allowed_assessment_types: list[
        Literal["collect_inventory", "review_configuration"]
    ] = Field(min_length=1, max_length=2)

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, values):
        pattern = re.compile(
            r"^(?=.{1,253}$)"
            r"(?:[a-zA-Z0-9]"
            r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
            r"[a-zA-Z]{2,63}$"
        )

        normalized = []

        for value in values:
            value = value.strip().lower().rstrip(".")

            if "*" in value or not pattern.fullmatch(value):
                raise ValueError(
                    "Domains must be exact valid domain names. "
                    "Wildcards are not permitted."
                )

            normalized.append(value)

        if len(normalized) != len(set(normalized)):
            raise ValueError("Duplicate domains are not permitted.")

        return normalized

    @field_validator("ip_addresses")
    @classmethod
    def validate_ip_addresses(cls, values):
        normalized = []

        for value in values:
            value = value.strip()

            try:
                normalized.append(str(ipaddress.ip_address(value)))
            except ValueError as exc:
                raise ValueError(
                    "Every IP address must be a valid individual IP address."
                ) from exc

        if len(normalized) != len(set(normalized)):
            raise ValueError("Duplicate IP addresses are not permitted.")

        return normalized

    @field_validator("excluded_targets")
    @classmethod
    def validate_excluded_targets(cls, values):
        normalized = []

        for value in values:
            value = value.strip().lower()

            try:
                normalized.append(str(ipaddress.ip_address(value)))
                continue
            except ValueError:
                pass

            if "*" in value or "." not in value:
                raise ValueError(
                    "Excluded targets must be exact domain names or IP addresses."
                )

            normalized.append(value.rstrip("."))

        if len(normalized) != len(set(normalized)):
            raise ValueError("Duplicate excluded targets are not permitted.")

        return normalized

    @model_validator(mode="after")
    def validate_scope(self):
        if not self.domains and not self.ip_addresses:
            raise ValueError(
                "At least one explicitly allowed domain or IP address is required."
            )

        if len(self.allowed_assessment_types) != len(
            set(self.allowed_assessment_types)
        ):
            raise ValueError("Duplicate assessment types are not permitted.")

        return self


class AssetAuthorizationCreateRequest(BaseModel):
    evidence_type: Literal[
        "ownership_proof",
        "authorization_letter",
        "contract",
        "other",
    ]

    evidence_reference: str = Field(min_length=8, max_length=1000)

    scope: AuthorizationScope

    valid_from: datetime
    expires_at: datetime

    @field_validator("evidence_reference")
    @classmethod
    def validate_evidence_reference(cls, value):
        value = value.strip()

        if len(value) < 8:
            raise ValueError("Evidence reference is too short.")

        return value

    @model_validator(mode="after")
    def validate_validity_period(self):
        if (
            self.valid_from.tzinfo is None
            or self.valid_from.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError(
                "Validity timestamps must include a timezone."
            )

        if self.valid_from >= self.expires_at:
            raise ValueError(
                "Authorization expiration must be later than its start."
            )

        if self.expires_at <= datetime.now(timezone.utc):
            raise ValueError(
                "Authorization expiration must be in the future."
            )

        return self


class AssetAuthorizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    asset_id: str
    status: str
    submitted_by: str
    reviewed_by: str | None
    evidence_type: str
    scope: dict
    valid_from: datetime
    expires_at: datetime
    decision_reason: str | None
    created_at: datetime
class AssetAuthorizationDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()

        if len(value) < 5:
            raise ValueError("Decision reason must contain at least 5 characters.")

        return value


class AuthorizationLifecycleRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_lifecycle_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("Lifecycle reason must contain at least 5 characters.")
        return value
