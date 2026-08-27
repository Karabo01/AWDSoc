"""The cross-tenant queue and the case view.

This is the product. Everything else is secondary, and the queue is one component
for two audiences: a staff token gets the tenant chip and the switcher, a client
token gets the same list without them. Do not build two.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app import audit
from app.db import get_session
from app.deps.auth import CurrentUser, accessible_tenant_ids
from app.deps.tenancy import TenantScope, get_tenant_scope
from app.incidents import sla
from app.models import (
    Alert,
    AuditLog,
    Entity,
    Incident,
    IncidentComment,
    IncidentEntity,
    Tenant,
    User,
)
from app.models.incident import OPEN_STATUSES
from app.pagination import decode_cursor, encode_cursor
from app.schemas.alert import AlertPage, AlertSummary
from app.schemas.incident import (
    CommentCreate,
    CommentRead,
    EntityRead,
    IncidentDetail,
    IncidentPage,
    IncidentSummary,
    IncidentUpdate,
    TimelineEntry,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])

Session = Annotated[AsyncSession, Depends(get_session)]
Scope = Annotated[TenantScope, Depends(get_tenant_scope)]

MAX_PAGE = 200
NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="No such incident."
)


async def _scoped(
    stmt: Select, session: AsyncSession, user: User, scope: TenantScope
) -> Select:
    stmt = scope.apply(stmt, Incident.tenant_id)
    if scope.is_fleet_view:
        allowed = await accessible_tenant_ids(session, user)
        if allowed is not None:
            stmt = stmt.where(Incident.tenant_id.in_(allowed))
    return stmt


def _summary(
    incident: Incident, tenant: Tenant | None, assignee: User | None, now: datetime
) -> IncidentSummary:
    payload = IncidentSummary.model_validate(incident)
    if tenant is not None:
        payload.tenant_name = tenant.name
        payload.tenant_slug = tenant.slug
        payload.tenant_colour = tenant.colour
    if assignee is not None:
        payload.assignee_name = assignee.full_name
    # Derived, never stored: a breach flag written by a worker sweep can lag,
    # and a lagging breach flag is worse than none.
    payload.response_breached = sla.response_breached(incident, now=now)
    payload.resolution_breached = sla.resolution_breached(incident, now=now)
    return payload


async def _load(
    session: AsyncSession, user: User, scope: TenantScope, incident_id: uuid.UUID
) -> tuple[Incident, Tenant, User | None]:
    assignee = aliased(User)
    stmt = (
        select(Incident, Tenant, assignee)
        .join(Tenant, Tenant.id == Incident.tenant_id)
        .join(assignee, assignee.id == Incident.assignee_id, isouter=True)
        .where(Incident.id == incident_id)
    )
    stmt = await _scoped(stmt, session, user, scope)
    row = (await session.execute(stmt)).first()
    if row is None:
        # Identical whether it does not exist or belongs to another tenant.
        raise NOT_FOUND
    return row


@router.get("", response_model=IncidentPage)
async def list_incidents(
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    cursor: str | None = None,
    status_in: Annotated[list[str] | None, Query(alias="status")] = None,
    severity_min: Annotated[int | None, Query(ge=0, le=15)] = None,
    assignee: Annotated[str | None, Query()] = None,
    entity_type: str | None = None,
    entity_value: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    open_only: bool = False,
) -> IncidentPage:
    assignee_user = aliased(User)
    stmt = (
        select(Incident, Tenant, assignee_user)
        .join(Tenant, Tenant.id == Incident.tenant_id)
        .join(assignee_user, assignee_user.id == Incident.assignee_id, isouter=True)
    )
    stmt = await _scoped(stmt, session, user, scope)

    if open_only:
        stmt = stmt.where(Incident.status.in_(OPEN_STATUSES))
    if status_in:
        stmt = stmt.where(Incident.status.in_(status_in))
    if severity_min is not None:
        stmt = stmt.where(Incident.severity >= severity_min)
    if assignee == "me":
        stmt = stmt.where(Incident.assignee_id == user.id)
    elif assignee == "unassigned":
        stmt = stmt.where(Incident.assignee_id.is_(None))
    elif assignee:
        try:
            stmt = stmt.where(Incident.assignee_id == uuid.UUID(assignee))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assignee must be a user id, 'me', or 'unassigned'.",
            ) from exc
    if from_ is not None:
        stmt = stmt.where(Incident.last_seen >= from_)
    if to is not None:
        stmt = stmt.where(Incident.last_seen <= to)
    if q:
        stmt = stmt.where(
            or_(Incident.title.ilike(f"%{q}%"), Incident.classification.ilike(f"%{q}%"))
        )
    if entity_type or entity_value:
        if not (entity_type and entity_value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pivoting needs both entity_type and entity_value.",
            )
        stmt = stmt.where(
            Incident.id.in_(
                select(IncidentEntity.incident_id)
                .join(Entity, Entity.id == IncidentEntity.entity_id)
                .where(Entity.type == entity_type, Entity.value == entity_value)
            )
        )

    if cursor:
        last_seen, last_id = decode_cursor(cursor)
        stmt = stmt.where((Incident.last_seen, Incident.id) < (last_seen, last_id))

    stmt = stmt.order_by(Incident.last_seen.desc(), Incident.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    now = datetime.now(UTC)
    items = [_summary(i, t, a, now) for i, t, a in rows]
    next_cursor = (
        encode_cursor(rows[-1][0].last_seen, rows[-1][0].id) if has_more and rows else None
    )
    return IncidentPage(items=items, next_cursor=next_cursor)


@router.get("/by-number/{tenant_slug}/{number}", response_model=IncidentDetail)
async def get_incident_by_number(
    tenant_slug: str,
    number: int,
    user: CurrentUser,
    session: Session,
    scope: Scope,
) -> IncidentDetail:
    """Shareable case address: an analyst says "acme-corp 42", not a UUID.

    Declared before the `/{incident_id}` route so "by-number" is not parsed as an
    id. Still tenant-scoped from the token: naming a slug you cannot see is a 404,
    exactly as if the case did not exist.
    """
    stmt = (
        select(Incident.id)
        .join(Tenant, Tenant.id == Incident.tenant_id)
        .where(Tenant.slug == tenant_slug, Incident.number == number)
    )
    stmt = await _scoped(stmt, session, user, scope)
    incident_id = await session.scalar(stmt)
    if incident_id is None:
        raise NOT_FOUND
    return await get_incident(incident_id, user, session, scope)


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident(
    incident_id: uuid.UUID, user: CurrentUser, session: Session, scope: Scope
) -> IncidentDetail:
    incident, tenant, assignee = await _load(session, user, scope, incident_id)
    now = datetime.now(UTC)
    detail = IncidentDetail.model_validate(incident)
    summary = _summary(incident, tenant, assignee, now)
    for field in (
        "tenant_name",
        "tenant_slug",
        "tenant_colour",
        "assignee_name",
        "response_breached",
        "resolution_breached",
    ):
        setattr(detail, field, getattr(summary, field))
    return detail


@router.patch("/{incident_id}", response_model=IncidentDetail)
async def update_incident(
    incident_id: uuid.UUID,
    payload: IncidentUpdate,
    user: CurrentUser,
    session: Session,
    scope: Scope,
) -> IncidentDetail:
    if user.role == "client_viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Read-only access."
        )

    incident, _tenant, _assignee = await _load(session, user, scope, incident_id)
    now = datetime.now(UTC)
    changes: dict = {}

    if payload.assign_to_me:
        incident.assignee_id = user.id
        changes["assignee_id"] = str(user.id)
        if sla.mark_first_response(incident, now=now):
            changes["first_response"] = True
    elif "assignee_id" in payload.model_fields_set:
        incident.assignee_id = payload.assignee_id
        changes["assignee_id"] = str(payload.assignee_id) if payload.assignee_id else None
        if payload.assignee_id and sla.mark_first_response(incident, now=now):
            changes["first_response"] = True

    if payload.title is not None and payload.title != incident.title:
        changes["title"] = payload.title
        incident.title = payload.title
    if payload.classification is not None:
        changes["classification"] = payload.classification
        incident.classification = payload.classification
    if payload.severity is not None and payload.severity != incident.severity:
        changes["severity"] = {"from": incident.severity, "to": payload.severity}
        incident.severity = payload.severity

    if payload.status is not None and payload.status != incident.status:
        policy = await sla.policy_for(session, incident.tenant_id)
        detail = sla.apply_status_transition(incident, payload.status, now=now)
        changes["status"] = detail
        # A manual severity change on an unanswered case re-tightens the clock.
        if "severity" in changes:
            sla.apply_on_escalation(incident, sla.band_for(policy, incident.severity))

    if not changes:
        return await get_incident(incident_id, user, session, scope)

    incident.updated_at = now
    await audit.record(
        session,
        action="incident.updated",
        target_type="incident",
        target_id=incident.id,
        tenant_id=incident.tenant_id,
        user_id=user.id,
        detail=changes,
    )
    await session.commit()
    return await get_incident(incident_id, user, session, scope)


@router.get("/{incident_id}/alerts", response_model=AlertPage)
async def incident_alerts(
    incident_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    cursor: str | None = None,
) -> AlertPage:
    incident, tenant, _ = await _load(session, user, scope, incident_id)

    stmt = select(Alert).where(
        Alert.tenant_id == incident.tenant_id, Alert.incident_id == incident.id
    )
    if cursor:
        last_timestamp, last_id = decode_cursor(cursor)
        stmt = stmt.where((Alert.timestamp, Alert.id) < (last_timestamp, last_id))
    stmt = stmt.order_by(Alert.timestamp.desc(), Alert.id.desc()).limit(limit + 1)

    alerts = list(await session.scalars(stmt))
    has_more = len(alerts) > limit
    alerts = alerts[:limit]

    items = []
    for alert in alerts:
        summary = AlertSummary.model_validate(alert)
        summary.tenant_name = tenant.name
        summary.tenant_slug = tenant.slug
        summary.tenant_colour = tenant.colour
        items.append(summary)

    next_cursor = (
        encode_cursor(alerts[-1].timestamp, alerts[-1].id) if has_more and alerts else None
    )
    return AlertPage(items=items, next_cursor=next_cursor)


@router.get("/{incident_id}/entities", response_model=list[EntityRead])
async def incident_entities(
    incident_id: uuid.UUID, user: CurrentUser, session: Session, scope: Scope
) -> list[EntityRead]:
    incident, _tenant, _assignee = await _load(session, user, scope, incident_id)
    rows = (
        await session.execute(
            select(Entity, IncidentEntity.role)
            .join(IncidentEntity, IncidentEntity.entity_id == Entity.id)
            .where(IncidentEntity.incident_id == incident.id)
            .order_by(Entity.type, Entity.value)
        )
    ).all()
    out = []
    for entity, role in rows:
        read = EntityRead.model_validate(entity)
        read.role = role
        out.append(read)
    return out


@router.get("/{incident_id}/comments", response_model=list[CommentRead])
async def list_comments(
    incident_id: uuid.UUID, user: CurrentUser, session: Session, scope: Scope
) -> list[CommentRead]:
    incident, _tenant, _assignee = await _load(session, user, scope, incident_id)

    stmt = (
        select(IncidentComment, User)
        .join(User, User.id == IncidentComment.user_id)
        .where(IncidentComment.incident_id == incident.id)
        .order_by(IncidentComment.created_at)
    )
    # An analyst's working notes and a client-facing update are different things.
    if not user.is_staff:
        stmt = stmt.where(IncidentComment.visibility == "client")

    out = []
    for comment, author in (await session.execute(stmt)).all():
        read = CommentRead.model_validate(comment)
        read.author_name = author.full_name
        out.append(read)
    return out


@router.post(
    "/{incident_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    incident_id: uuid.UUID,
    payload: CommentCreate,
    user: CurrentUser,
    session: Session,
    scope: Scope,
) -> CommentRead:
    if user.role == "client_viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Read-only access."
        )
    incident, _tenant, _assignee = await _load(session, user, scope, incident_id)

    visibility = payload.visibility
    if not user.is_staff:
        # A client cannot write into AWDTECH's internal notes.
        visibility = "client"

    now = datetime.now(UTC)
    comment = IncidentComment(
        incident_id=incident.id,
        user_id=user.id,
        body=payload.body,
        visibility=visibility,
        created_at=now,
    )
    session.add(comment)

    detail: dict = {"visibility": visibility}
    if user.is_staff and sla.mark_first_response(incident, now=now):
        detail["first_response"] = True
    incident.updated_at = now

    await audit.record(
        session,
        action="incident.commented",
        target_type="incident",
        target_id=incident.id,
        tenant_id=incident.tenant_id,
        user_id=user.id,
        detail=detail,
    )
    await session.commit()
    await session.refresh(comment)

    read = CommentRead.model_validate(comment)
    read.author_name = user.full_name
    return read


@router.get("/{incident_id}/timeline", response_model=list[TimelineEntry])
async def timeline(
    incident_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[TimelineEntry]:
    """Alerts, comments and audit entries merged into one chronology."""
    incident, _tenant, _assignee = await _load(session, user, scope, incident_id)
    entries: list[TimelineEntry] = []

    alerts = await session.scalars(
        select(Alert)
        .where(Alert.tenant_id == incident.tenant_id, Alert.incident_id == incident.id)
        .order_by(Alert.timestamp.desc())
        .limit(limit)
    )
    for alert in alerts:
        entries.append(
            TimelineEntry(
                at=alert.timestamp,
                kind="alert",
                summary=alert.rule_desc,
                detail={
                    "alert_id": str(alert.id),
                    "rule_id": alert.rule_id,
                    "rule_level": alert.rule_level,
                    "agent_name": alert.agent_name,
                },
            )
        )

    comment_stmt = (
        select(IncidentComment, User)
        .join(User, User.id == IncidentComment.user_id)
        .where(IncidentComment.incident_id == incident.id)
    )
    if not user.is_staff:
        comment_stmt = comment_stmt.where(IncidentComment.visibility == "client")
    for comment, author in (await session.execute(comment_stmt)).all():
        entries.append(
            TimelineEntry(
                at=comment.created_at,
                kind="comment",
                summary=f"{author.full_name} commented",
                detail={"body": comment.body, "visibility": comment.visibility},
            )
        )

    # Clients see that something happened, not the internal detail of it.
    if user.is_staff:
        audit_rows = (
            await session.execute(
                select(AuditLog, User)
                .join(User, User.id == AuditLog.user_id, isouter=True)
                .where(
                    AuditLog.target_type == "incident",
                    AuditLog.target_id == incident.id,
                )
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
        ).all()
        for entry, actor in audit_rows:
            entries.append(
                TimelineEntry(
                    at=entry.created_at,
                    kind="audit",
                    summary=f"{actor.full_name if actor else 'System'}: {entry.action}",
                    detail=entry.detail or {},
                )
            )

    entries.sort(key=lambda e: e.at, reverse=True)
    return entries[:limit]
