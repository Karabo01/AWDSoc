"""Platform administration. platform_admin only."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.config import settings
from app.db import get_session
from app.deps.auth import CurrentUser
from app.deps.rbac import require_roles
from app.models import Alert, Tenant
from app.queue import get_arq_pool
from app.redis_client import get_redis
from app.workers.reprocess import progress_key

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_roles("platform_admin"))],
)

Session = Annotated[AsyncSession, Depends(get_session)]


class ReprocessRequest(BaseModel):
    # Omitted means every tenant.
    tenant_id: uuid.UUID | None = None
    from_: datetime = Field(alias="from")
    to: datetime
    # Omitted means the currently configured map version.
    map_version: int | None = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _range_is_sane(self) -> "ReprocessRequest":
        if self.to <= self.from_:
            raise ValueError("`to` must be after `from`")
        return self


class ReprocessAccepted(BaseModel):
    job_id: str
    estimated_rows: int
    map_version: int
    # Replay only reaches back as far as retention.
    truncated_to_retention: bool


class ReprocessProgress(BaseModel):
    job_id: str
    status: str
    updated: int = 0
    failed: int = 0


@router.post("/reprocess", response_model=ReprocessAccepted, status_code=status.HTTP_202_ACCEPTED)
async def reprocess(
    payload: ReprocessRequest, user: CurrentUser, session: Session
) -> ReprocessAccepted:
    """Re-run normalisation from `raw` across a time range.

    `raw` is never mutated, so this is always safe to repeat. It runs on the
    worker: a range covering a month of a busy cohort is not a request.
    """
    version = payload.map_version or settings.normalisation_map_version

    horizon = datetime.now(UTC) - timedelta(days=settings.alert_retention_days)
    start = max(payload.from_, horizon)

    count_stmt = (
        select(func.count())
        .select_from(Alert)
        .where(Alert.timestamp >= start, Alert.timestamp <= payload.to)
    )
    if payload.tenant_id is not None:
        if await session.get(Tenant, payload.tenant_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such client.")
        count_stmt = count_stmt.where(Alert.tenant_id == payload.tenant_id)
    estimated = int(await session.scalar(count_stmt) or 0)

    job_id = uuid.uuid4().hex
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "reprocess_alerts",
        job_id=job_id,
        tenant_id=str(payload.tenant_id) if payload.tenant_id else None,
        start=start.isoformat(),
        end=payload.to.isoformat(),
        target_version=version,
    )

    await audit.record(
        session,
        action="admin.reprocess_started",
        target_type="alerts",
        tenant_id=payload.tenant_id,
        user_id=user.id,
        detail={
            "job_id": job_id,
            "from": start.isoformat(),
            "to": payload.to.isoformat(),
            "map_version": version,
            "estimated_rows": estimated,
        },
    )
    await session.commit()

    return ReprocessAccepted(
        job_id=job_id,
        estimated_rows=estimated,
        map_version=version,
        truncated_to_retention=start > payload.from_,
    )


@router.get("/reprocess/{job_id}", response_model=ReprocessProgress)
async def reprocess_progress(job_id: str) -> ReprocessProgress:
    fields = await get_redis().hgetall(progress_key(job_id))
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such job, or its progress has expired.",
        )
    return ReprocessProgress(
        job_id=job_id,
        status=fields.get("status", "unknown"),
        updated=int(fields.get("updated", 0)),
        failed=int(fields.get("failed", 0)),
    )
