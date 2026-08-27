"""Agent, rule and coverage schemas.

Everything here describes a *cache* of a client's manager. `synced_at` is on the
summary rather than tucked into a detail view for exactly that reason: an analyst
must never have to wonder whether a green "active" is current or four hours old.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.types import NetAddr


class AgentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: uuid.UUID
    tenant_name: str | None = None
    tenant_slug: str | None = None
    tenant_colour: str | None = None

    agent_id: str
    name: str
    # inet arrives from asyncpg as an IPv4Address, not a string.
    ip: NetAddr | None = None
    os_platform: str | None = None
    os_name: str | None = None
    version: str | None = None
    status: str | None = None
    groups: list[str] = Field(default_factory=list)
    last_keepalive: datetime | None = None
    synced_at: datetime


class AgentDetail(AgentSummary):
    """Adds what the console knows that the manager does not: how much this agent
    has actually sent us."""

    alerts_24h: int = 0
    open_incidents: int = 0
    last_alert_at: datetime | None = None
    # Non-null when this agent id is cached under more than one tenant on the same
    # manager - a group misconfiguration, and a cross-tenant leak.
    misgrouped_with: list[str] | None = None


class AgentPage(BaseModel):
    items: list[AgentSummary]
    next_cursor: str | None = None


class SyncReport(BaseModel):
    tenant_id: uuid.UUID
    tenant_slug: str | None = None
    ok: bool
    synced: int = 0
    removed: int = 0
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RuleRead(BaseModel):
    """Read through to the tenant's manager, cached for an hour.

    `stale` is true when the manager could not be reached and this is a cached
    copy being served anyway - the alternative is a blank panel on a case the
    analyst is trying to work.
    """

    id: int
    level: int | None = None
    description: str | None = None
    groups: list[str] = Field(default_factory=list)
    mitre_ids: list[str] = Field(default_factory=list)
    pci_dss: list[str] = Field(default_factory=list)
    gdpr: list[str] = Field(default_factory=list)
    hipaa: list[str] = Field(default_factory=list)
    nist_800_53: list[str] = Field(default_factory=list)
    filename: str | None = None
    relative_dirname: str | None = None
    cached_at: datetime | None = None
    stale: bool = False


class TechniqueCoverage(BaseModel):
    technique_id: str
    alert_count: int
    incident_count: int
    last_seen: datetime | None = None
    max_severity: int = 0


class TacticCoverage(BaseModel):
    tactic: str
    technique_count: int
    alert_count: int


class CoverageReport(BaseModel):
    """What we have actually detected, not what we could detect.

    This is deliberately a coverage report over observed alerts rather than over
    a client's ruleset. A rule that exists but has never fired tells an analyst
    nothing about their exposure; a technique that fired forty times last week
    tells them a great deal.
    """

    since: datetime
    techniques: list[TechniqueCoverage] = Field(default_factory=list)
    tactics: list[TacticCoverage] = Field(default_factory=list)
    unmapped_alerts: int = 0
    total_alerts: int = 0
