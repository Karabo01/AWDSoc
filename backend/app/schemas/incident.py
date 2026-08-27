import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["new", "active", "pending", "resolved", "false_positive"]
Visibility = Literal["internal", "client"]


class IncidentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str | None = None
    tenant_slug: str | None = None
    tenant_colour: str | None = None

    number: int
    title: str
    status: Status
    severity: int
    classification: str | None = None
    assignee_id: uuid.UUID | None = None
    assignee_name: str | None = None

    first_seen: datetime
    last_seen: datetime
    alert_count: int

    # SLA. `sla_paused_at` non-null means the clock is stopped awaiting the
    # client; a stopped countdown must never render as a running one.
    sla_respond_by: datetime | None = None
    sla_resolve_by: datetime | None = None
    sla_paused_at: datetime | None = None
    sla_paused_seconds: int = 0
    first_response_at: datetime | None = None
    response_breached: bool = False
    resolution_breached: bool = False

    created_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentSummary):
    fingerprint: str
    rule_summary: dict = Field(default_factory=dict)
    # Trimmed snapshot, so a closed case still reads after its alerts age out.
    evidence: dict = Field(default_factory=dict)
    related_incident_id: uuid.UUID | None = None
    closed_at: datetime | None = None


class IncidentPage(BaseModel):
    items: list[IncidentSummary]
    next_cursor: str | None = None


class IncidentUpdate(BaseModel):
    status: Status | None = None
    severity: int | None = Field(default=None, ge=0, le=15)
    # Explicit null clears the assignee, so this is a sentinel-free tri-state.
    assignee_id: uuid.UUID | None = None
    assign_to_me: bool = False
    title: str | None = Field(default=None, min_length=1, max_length=200)
    classification: str | None = Field(default=None, max_length=200)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    visibility: Visibility = "internal"


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    user_id: uuid.UUID
    author_name: str | None = None
    body: str
    visibility: Visibility
    created_at: datetime


class TimelineEntry(BaseModel):
    at: datetime
    kind: Literal["alert", "comment", "audit"]
    summary: str
    detail: dict = Field(default_factory=dict)


class EntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    value: str
    first_seen: datetime
    last_seen: datetime
    alert_count: int
    role: str | None = None
