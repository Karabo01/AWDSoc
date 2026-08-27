"""Entity index schemas.

An entity is a tenant-scoped observation, not a global object. The same IP seen
by two clients is two rows with two independent note fields, because one client's
analyst must never read another's working notes.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EntityType = Literal["ip", "user", "host", "hash", "process", "file"]


class EntitySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    # Present so a staff fleet view can label every row without a second call.
    tenant_name: str | None = None
    tenant_slug: str | None = None
    tenant_colour: str | None = None

    type: str
    value: str
    first_seen: datetime
    last_seen: datetime
    alert_count: int
    has_notes: bool = False


class EntityDetail(EntitySummary):
    notes: str | None = None
    # Cheap counts the detail header shows; the lists themselves are paged.
    open_incident_count: int = 0
    incident_count: int = 0


class EntityNotesUpdate(BaseModel):
    """The only mutable field on an entity. Everything else is observed."""

    notes: str | None = Field(default=None, max_length=8000)


class EntityPage(BaseModel):
    items: list[EntitySummary]
    next_cursor: str | None = None
