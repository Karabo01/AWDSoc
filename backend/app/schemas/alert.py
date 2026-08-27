import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.types import StrList

EntityType = Literal["ip", "user", "host", "hash"]


class AlertSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    # Present so a staff fleet view can label every row without a second call.
    tenant_name: str | None = None
    tenant_slug: str | None = None
    tenant_colour: str | None = None

    timestamp: datetime
    rule_id: int
    rule_level: int
    rule_desc: str
    rule_groups: list[str] = Field(default_factory=list)
    mitre_ids: list[str] = Field(default_factory=list)
    agent_id: str | None = None
    agent_name: str | None = None
    incident_id: uuid.UUID | None = None
    map_version: int


class AlertDetail(AlertSummary):
    received_at: datetime
    wazuh_id: str
    mitre_tactics: list[str] = Field(default_factory=list)
    fingerprint: str
    # The inspector shows these side by side. `raw` is never mutated.
    ecs: dict
    raw: dict
    # inet[] arrives from asyncpg as IPv4Address objects, not strings.
    related_ip: StrList = Field(default_factory=list)
    related_user: StrList = Field(default_factory=list)
    related_host: StrList = Field(default_factory=list)
    related_hash: StrList = Field(default_factory=list)


class AlertPage(BaseModel):
    items: list[AlertSummary]
    next_cursor: str | None = None
