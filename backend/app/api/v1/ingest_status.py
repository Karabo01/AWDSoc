"""Is ingest working? Staff-only, and the first thing to look at after installing
the integrator on a client's manager.

Separate from the ingest webhook itself so that nothing on the public, unauthenticated
path shares a router with something that reads the database.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps.auth import CurrentUser, accessible_tenant_ids
from app.deps.rbac import require_roles
from app.ingest.stream import stream_depth
from app.models import Alert, IngestStat, Tenant

router = APIRouter(
    prefix="/ingest",
    tags=["ingest"],
    dependencies=[Depends(require_roles("platform_admin", "soc_analyst"))],
)

Session = Annotated[AsyncSession, Depends(get_session)]


class TenantIngest(BaseModel):
    tenant_id: str
    slug: str
    name: str
    alerts_today: int
    bytes_today: int
    last_alert_at: datetime | None
    # Silence is the failure mode that looks like success. An onboarded client
    # that has never delivered is almost always a misconfigured integration.
    silent: bool


class IngestStatus(BaseModel):
    backlog: int
    tenants: list[TenantIngest]


@router.get("/status", response_model=IngestStatus)
async def ingest_status(user: CurrentUser, session: Session) -> IngestStatus:
    allowed = await accessible_tenant_ids(session, user)

    tenants_query = select(Tenant).order_by(Tenant.name)
    if allowed is not None:
        tenants_query = tenants_query.where(Tenant.id.in_(allowed))
    tenants = list(await session.scalars(tenants_query))

    today = datetime.now(UTC).date()
    stats = {
        row.tenant_id: row
        for row in await session.scalars(
            select(IngestStat).where(IngestStat.day == today)
        )
    }

    # Bounded to the last 48h so this never scans beyond two partitions.
    since = datetime.now(UTC) - timedelta(hours=48)
    latest = dict(
        (
            await session.execute(
                select(Alert.tenant_id, func.max(Alert.timestamp))
                .where(Alert.timestamp >= since)
                .group_by(Alert.tenant_id)
            )
        ).all()
    )

    rows = []
    for tenant in tenants:
        stat = stats.get(tenant.id)
        last_seen = latest.get(tenant.id)
        rows.append(
            TenantIngest(
                tenant_id=str(tenant.id),
                slug=tenant.slug,
                name=tenant.name,
                alerts_today=stat.alert_count if stat else 0,
                bytes_today=stat.bytes_in if stat else 0,
                last_alert_at=last_seen,
                silent=last_seen is None and tenant.status == "active",
            )
        )

    return IngestStatus(backlog=await stream_depth(), tenants=rows)
