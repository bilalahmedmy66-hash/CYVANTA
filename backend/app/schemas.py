from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
