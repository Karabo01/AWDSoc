import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class RefreshRequest(BaseModel):
    refresh_token: str


class SwitchTenantRequest(BaseModel):
    # null means the all-clients fleet view.
    tenant_id: uuid.UUID | None = None


class TenantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    status: str
    colour: str | None = None


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_staff: bool
    tenant_id: uuid.UUID | None
    active_tenant: uuid.UUID | None = None
    # Staff only. Empty for client users, who never see a switcher.
    tenants: list[TenantSummary] = []
