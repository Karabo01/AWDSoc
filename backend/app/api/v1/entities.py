"""The entity index and its pivots.

Two data structures answer two different questions and both are needed. The
`related.*` arrays on `alerts` answer "which alerts touched this value" through a
GIN index, fast enough to run on every page load. The `entities` rows answer
"what have we seen of this value, and what did we say about it" - first seen,
last seen, the running count, and the analyst's notes.

Every row is tenant-scoped. The same IP observed by two clients is two rows, so
one client's notes can never surface in another's console.

Values arrive in the path as `{value:path}` because a file or process entity can
contain a slash. The sub-resource routes are declared before the bare detail
route so the router matches `/1.2.3.4/alerts` as a pivot rather than as an entity
literally named `1.2.3.4/alerts`.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app import audit
from app.api.v1.incidents import summarise
from app.db import get_session
from app.deps.auth import CurrentUser, accessible_tenant_ids
from app.deps.tenancy import TenantScope, get_tenant_scope
from app.models import Alert, Entity, Incident, IncidentEntity, Tenant, User
from app.models.incident import OPEN_STATUSES
from app.pagination import decode_cursor, encode_cursor
from app.schemas.alert import AlertPage, AlertSummary
from app.schemas.entity import (
    EntityDetail,
    EntityNotesUpdate,
    EntityPage,
    EntitySummary,
    EntityType,
)
from app.schemas.incident import IncidentPage

router = APIRouter(prefix="/entities", tags=["entities"])

Session = Annotated[AsyncSession, Depends(get_session)]
Scope = Annotated[TenantScope, Depends(get_tenant_scope)]

MAX_PAGE = 200
NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="We have not seen that entity."
)

# The alert pivot exists only for the four types that have an indexed array on
# `alerts`. Anything else would be a sequential scan of a partitioned table.
PIVOT_COLUMNS = {
    "ip": Alert.related_ip,
    "user": Alert.related_user,
    "host": Alert.related_host,
    "hash": Alert.related_hash,
}


async def _scoped(
    stmt: Select, session: AsyncSession, user: User, scope: TenantScope, column
) -> Select:
    """Two layers, both required - see the note in `alerts.py`."""
    stmt = scope.apply(stmt, column)
    if scope.is_fleet_view:
        allowed = await accessible_tenant_ids(session, user)
        if allowed is not None:
            stmt = stmt.where(column.in_(allowed))
    return stmt


def _summarise(entity: Entity, tenant: Tenant | None) -> EntitySummary:
    payload = EntitySummary.model_validate(entity)
    payload.has_notes = bool(entity.notes and entity.notes.strip())
    if tenant is not None:
        payload.tenant_name = tenant.name
        payload.tenant_slug = tenant.slug
        payload.tenant_colour = tenant.colour
    return payload


async def _load(
    session: AsyncSession,
    user: User,
    scope: TenantScope,
    entity_type: str,
    value: str,
) -> tuple[Entity, Tenant]:
    """Resolve one entity within the caller's tenancy.

    A fleet view can legitimately match the same value under several tenants.
    Rather than guess, it takes the most recently seen - the analyst is looking at
    a cross-client index and the freshest observation is the one they mean. A
    client token can only ever match one row.
    """
    stmt = (
        select(Entity, Tenant)
        .join(Tenant, Tenant.id == Entity.tenant_id)
        .where(Entity.type == entity_type, Entity.value == value)
    )
    stmt = await _scoped(stmt, session, user, scope, Entity.tenant_id)
    stmt = stmt.order_by(Entity.last_seen.desc()).limit(1)
    row = (await session.execute(stmt)).first()
    if row is None:
        raise NOT_FOUND
    return row[0], row[1]


@router.get("", response_model=EntityPage)
async def list_entities(
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    cursor: str | None = None,
    type_: Annotated[EntityType | None, Query(alias="type")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    last_seen_after: datetime | None = None,
    min_alerts: Annotated[int | None, Query(ge=1)] = None,
) -> EntityPage:
    stmt = select(Entity, Tenant).join(Tenant, Tenant.id == Entity.tenant_id)
    stmt = await _scoped(stmt, session, user, scope, Entity.tenant_id)

    if type_ is not None:
        stmt = stmt.where(Entity.type == type_)
    if last_seen_after is not None:
        stmt = stmt.where(Entity.last_seen >= last_seen_after)
    if min_alerts is not None:
        stmt = stmt.where(Entity.alert_count >= min_alerts)
    if q:
        # Backed by the trigram index added in 0004; without it this is a scan.
        stmt = stmt.where(Entity.value.ilike(f"%{q}%"))

    if cursor:
        last_seen, last_id = decode_cursor(cursor)
        stmt = stmt.where((Entity.last_seen, Entity.id) < (last_seen, last_id))

    stmt = stmt.order_by(Entity.last_seen.desc(), Entity.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(rows[-1][0].last_seen, rows[-1][0].id) if has_more and rows else None
    )
    return EntityPage(
        items=[_summarise(entity, tenant) for entity, tenant in rows],
        next_cursor=next_cursor,
    )


@router.get("/{type_}/{value:path}/alerts", response_model=AlertPage)
async def entity_alerts(
    type_: EntityType,
    value: str,
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    cursor: str | None = None,
) -> AlertPage:
    """The pivot: one indexed containment lookup, newest first."""
    column = PIVOT_COLUMNS.get(type_)
    if column is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Alerts cannot be pivoted by {type_} - only ip, user, host and "
            "hash are indexed on alerts.",
        )

    stmt = select(Alert, Tenant).join(Tenant, Tenant.id == Alert.tenant_id)
    stmt = await _scoped(stmt, session, user, scope, Alert.tenant_id)
    stmt = stmt.where(column.contains([value]))

    if cursor:
        last_timestamp, last_id = decode_cursor(cursor)
        stmt = stmt.where((Alert.timestamp, Alert.id) < (last_timestamp, last_id))

    stmt = stmt.order_by(Alert.timestamp.desc(), Alert.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for alert, tenant in rows:
        summary = AlertSummary.model_validate(alert)
        summary.tenant_name = tenant.name
        summary.tenant_slug = tenant.slug
        summary.tenant_colour = tenant.colour
        items.append(summary)

    next_cursor = (
        encode_cursor(rows[-1][0].timestamp, rows[-1][0].id) if has_more and rows else None
    )
    return AlertPage(items=items, next_cursor=next_cursor)


@router.get("/{type_}/{value:path}/incidents", response_model=IncidentPage)
async def entity_incidents(
    type_: EntityType,
    value: str,
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    cursor: str | None = None,
) -> IncidentPage:
    """Every case this value has appeared in, across the caller's tenancy."""
    assignee = aliased(User)
    stmt = (
        select(Incident, Tenant, assignee)
        .join(Tenant, Tenant.id == Incident.tenant_id)
        .join(assignee, assignee.id == Incident.assignee_id, isouter=True)
        .where(
            Incident.id.in_(
                select(IncidentEntity.incident_id)
                .join(Entity, Entity.id == IncidentEntity.entity_id)
                .where(Entity.type == type_, Entity.value == value)
            )
        )
    )
    stmt = await _scoped(stmt, session, user, scope, Incident.tenant_id)

    if cursor:
        last_seen, last_id = decode_cursor(cursor)
        stmt = stmt.where((Incident.last_seen, Incident.id) < (last_seen, last_id))

    stmt = stmt.order_by(Incident.last_seen.desc(), Incident.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    now = datetime.now(UTC)
    next_cursor = (
        encode_cursor(rows[-1][0].last_seen, rows[-1][0].id) if has_more and rows else None
    )
    return IncidentPage(
        items=[summarise(i, t, a, now) for i, t, a in rows], next_cursor=next_cursor
    )


@router.get("/{type_}/{value:path}", response_model=EntityDetail)
async def get_entity(
    type_: EntityType,
    value: str,
    user: CurrentUser,
    session: Session,
    scope: Scope,
) -> EntityDetail:
    entity, tenant = await _load(session, user, scope, type_, value)

    counts = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Incident.status.in_(OPEN_STATUSES)),
            )
            .select_from(IncidentEntity)
            .join(Incident, Incident.id == IncidentEntity.incident_id)
            .where(IncidentEntity.entity_id == entity.id)
        )
    ).one()

    detail = EntityDetail.model_validate(entity)
    detail.has_notes = bool(entity.notes and entity.notes.strip())
    detail.tenant_name = tenant.name
    detail.tenant_slug = tenant.slug
    detail.tenant_colour = tenant.colour
    detail.incident_count = counts[0]
    detail.open_incident_count = counts[1]
    return detail


@router.patch("/{type_}/{value:path}", response_model=EntityDetail)
async def update_entity(
    type_: EntityType,
    value: str,
    payload: EntityNotesUpdate,
    user: CurrentUser,
    session: Session,
    scope: Scope,
) -> EntityDetail:
    """Notes only. Nothing else about an entity is a matter of opinion."""
    if user.role == "client_viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not allow this action.",
        )

    entity, _tenant = await _load(session, user, scope, type_, value)

    before = entity.notes
    entity.notes = payload.notes
    await audit.record(
        session,
        action="entity.notes_updated",
        target_type="entity",
        target_id=entity.id,
        tenant_id=entity.tenant_id,
        user_id=user.id,
        # The note bodies stay out of the audit detail: an audit row is readable
        # by a client_admin and a note may be internal.
        detail={"type": entity.type, "value": entity.value, "had_notes": bool(before)},
    )
    await session.commit()

    return await get_entity(type_, value, user, session, scope)
