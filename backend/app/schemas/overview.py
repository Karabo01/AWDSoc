"""Overview schemas.

One shape serves both audiences. A client token gets a single-element `tenants`
list and `scope: "tenant"`; a staff fleet token gets one row per client and the
platform-level warnings. Building two overviews would guarantee they drift.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TenantOverview(BaseModel):
    tenant_id: uuid.UUID
    name: str
    slug: str
    colour: str | None = None
    status: str

    open_incidents: int = 0
    new_incidents: int = 0
    unassigned_incidents: int = 0
    # Severity 13+ on the Wazuh ramp: the ones that get someone out of bed.
    critical_open: int = 0
    response_breached: int = 0
    resolution_breached: int = 0
    # Open, unbreached, and inside the last hour of its response deadline.
    at_risk: int = 0
    # Clock stopped awaiting the client. Counted separately because these cannot
    # breach, and an analyst reading a queue needs to know why.
    awaiting_client: int = 0

    alerts_24h: int = 0
    last_alert_at: datetime | None = None
    # True when this client has never delivered an alert, or has gone quiet for
    # longer than a day. Almost always an integration problem, not a quiet week.
    silent: bool = False

    agents_total: int = 0
    agents_active: int = 0
    agents_disconnected: int = 0
    last_sync_at: datetime | None = None
    last_sync_error: str | None = None
    has_connection: bool = False
    has_sla: bool = False


class MisgroupedAgent(BaseModel):
    """The one cross-tenant leak ingest cannot catch - see `wazuh/sync.py`."""

    base_url: str
    agent_id: str
    agent_name: str | None = None
    tenant_slugs: list[str] = Field(default_factory=list)


class Overview(BaseModel):
    scope: str
    generated_at: datetime
    tenants: list[TenantOverview] = Field(default_factory=list)

    open_incidents: int = 0
    critical_open: int = 0
    response_breached: int = 0
    at_risk: int = 0
    alerts_24h: int = 0

    # Staff only. Empty for a client token, which must never learn that another
    # tenant exists at all.
    misgrouped_agents: list[MisgroupedAgent] = Field(default_factory=list)
    silent_tenants: list[str] = Field(default_factory=list)
