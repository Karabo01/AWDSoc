"""Alert list and inspector.

Tenant scoping comes from the token. A staff token with `active_tenant` null sees
every tenant it has access to; a client token sees exactly one. There is no
tenant parameter, and `tests/test_app.py` fails the build if one appears.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps.auth import CurrentUser, accessible_tenant_ids
from app.deps.tenancy import TenantScope, get_tenant_scope
from app.models import Alert, Tenant
from app.pagination import decode_cursor, encode_cursor
from app.schemas.alert import AlertDetail, AlertPage, AlertSummary, EntityType

router = APIRouter(prefix="/alerts", tags=["alerts"])

Session = Annotated[AsyncSession, Depends(get_session)]
Scope = Annotated[TenantScope, Depends(get_tenant_scope)]

MAX_PAGE = 200

# The pivot: one indexed containment lookup per entity type.
ENTITY_COLUMNS = {
    "ip": Alert.related_ip,
    "user": Alert.related_user,
    "host": Alert.related_host,
    "hash": Alert.related_hash,
}


async def scoped(
    stmt: Select, session: AsyncSession, user: CurrentUser, scope: TenantScope
) -> Select:
    """Apply the token's tenancy. Two layers, and both are required.

    `scope.apply` pins a single tenant when the token names one. The fleet view
    then narrows to the tenants this staff member may actually see - without it,
    a staff user narrowed by `staff_tenant_access` would read everything.
    """
    stmt = scope.apply(stmt, Alert.tenant_id)
    if scope.is_fleet_view:
        allowed = await accessible_tenant_ids(session, user)
        if allowed is not None:
            stmt = stmt.where(Alert.tenant_id.in_(allowed))
    return stmt


def _summary(alert: Alert, tenant: Tenant | None) -> AlertSummary:
    summary = AlertSummary.model_validate(alert)
    if tenant is not None:
        summary.tenant_name = tenant.name
        summary.tenant_slug = tenant.slug
        summary.tenant_colour = tenant.colour
    return summary


@router.get("", response_model=AlertPage)
async def list_alerts(
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    cursor: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    severity_min: Annotated[int | None, Query(ge=0, le=15)] = None,
    rule_id: int | None = None,
    agent_id: str | None = None,
    entity_type: EntityType | None = None,
    entity_value: str | None = None,
    # -1 finds rows whose normalisation threw; 0 finds rows M4 has not reached.
    map_version: int | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> AlertPage:
    stmt = select(Alert, Tenant).join(Tenant, Tenant.id == Alert.tenant_id)
    stmt = await scoped(stmt, session, user, scope)

    if from_ is not None:
        stmt = stmt.where(Alert.timestamp >= from_)
    if to is not None:
        stmt = stmt.where(Alert.timestamp <= to)
    if severity_min is not None:
        stmt = stmt.where(Alert.rule_level >= severity_min)
    if rule_id is not None:
        stmt = stmt.where(Alert.rule_id == rule_id)
    if agent_id is not None:
        stmt = stmt.where(Alert.agent_id == agent_id)
    if map_version is not None:
        stmt = stmt.where(Alert.map_version == map_version)
    if q:
        stmt = stmt.where(Alert.rule_desc.ilike(f"%{q}%"))

    if entity_type is not None or entity_value is not None:
        if not (entity_type and entity_value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pivoting needs both entity_type and entity_value.",
            )
        stmt = stmt.where(ENTITY_COLUMNS[entity_type].contains([entity_value]))

    if cursor:
        last_timestamp, last_id = decode_cursor(cursor)
        # Keyset, not offset: a page boundary stays correct while rows arrive.
        stmt = stmt.where((Alert.timestamp, Alert.id) < (last_timestamp, last_id))

    stmt = stmt.order_by(Alert.timestamp.desc(), Alert.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [_summary(alert, tenant) for alert, tenant in rows]
    next_cursor = (
        encode_cursor(rows[-1][0].timestamp, rows[-1][0].id) if has_more and rows else None
    )
    return AlertPage(items=items, next_cursor=next_cursor)


@router.get("/{alert_id}", response_model=AlertDetail)
async def get_alert(
    alert_id: uuid.UUID, user: CurrentUser, session: Session, scope: Scope
) -> AlertDetail:
    """`id` is the leading column of the primary key, so this is an index lookup
    even though the table is partitioned by timestamp."""
    stmt = (
        select(Alert, Tenant).join(Tenant, Tenant.id == Alert.tenant_id).where(Alert.id == alert_id)
    )
    stmt = await scoped(stmt, session, user, scope)
    row = (await session.execute(stmt)).first()
    if row is None:
        # Deliberately identical whether the alert does not exist or belongs to
        # another tenant. A 403 here would confirm the id.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such alert.")

    alert, tenant = row
    detail = AlertDetail.model_validate(alert)
    detail.tenant_name = tenant.name
    detail.tenant_slug = tenant.slug
    detail.tenant_colour = tenant.colour
    return detail
