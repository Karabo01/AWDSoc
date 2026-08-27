"""User administration schemas.

No response model in this file carries a password or a password hash, and
`tests/test_secret_exposure.py` walks the OpenAPI schema to keep it that way. A
generated password appears exactly once, in `UserCreated`, which is named to make
a reviewer look twice.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["platform_admin", "soc_analyst", "client_admin", "client_viewer"]
CLIENT_ROLES = ("client_admin", "client_viewer")


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_staff: bool
    is_active: bool
    tenant_id: uuid.UUID | None = None
    tenant_name: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    # Required for a client role, rejected for a staff role. The tenancy check
    # constraint on `users` makes the wrong combination unstorable anyway; this
    # turns a 500 into a message that says what to fix.
    tenant_id: uuid.UUID | None = None
    # Omitted means one is generated and returned once.
    password: str | None = Field(default=None, min_length=12, max_length=256)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None


class UserCreated(BaseModel):
    """The one and only time a password is returned, and the only response model
    in the API that carries one.

    Creation and reset both return this, so there is exactly one shape a reviewer
    has to keep an eye on - `tests/test_secret_exposure.py` names it explicitly
    and fails if a second one appears. The password cannot be read back; a reset
    is the only recovery, which is the same contract as the tenant ingest secret.
    """

    user: UserRead
    password: str | None = None
