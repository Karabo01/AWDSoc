"""The audit log endpoint.

platform_admin sees everything they have access to; client_admin sees their own
tenant. Nobody else sees it at all - an audit trail a subject can read but not
write is still a disclosure surface.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps.auth import CurrentUser, accessible_tenant_ids
from app.deps.rbac import require_roles
from app.deps.tenancy import TenantScope, get_tenant_scope
from app.models import AuditLog, User

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(require_roles("platform_admin", "client_admin"))],
)

Session = Annotated[AsyncSession, Depends(get_session)]
Scope = Annotated[TenantScope, Depends(get_tenant_scope)]


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: uuid.UUID | None
    user_id: uuid.UUID | None
    actor_name: str | None = None
    action: str
    target_type: str
    target_id: uuid.UUID | None
    detail: dict
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEntry]
    next_before_id: int | None = None


@router.get("", response_model=AuditPage)
async def list_audit(
    user: CurrentUser,
    session: Session,
    scope: Scope,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: int | None = None,
    action: str | None = None,
    target_id: uuid.UUID | None = None,
) -> AuditPage:
    stmt = select(AuditLog, User).join(User, User.id == AuditLog.user_id, isouter=True)
    stmt = scope.apply(stmt, AuditLog.tenant_id)

    if scope.is_fleet_view:
        allowed = await accessible_tenant_ids(session, user)
        if allowed is not None:
            stmt = stmt.where(AuditLog.tenant_id.in_(allowed))
    elif not user.is_staff and user.role != "client_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not available for your role."
        )

    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    if before_id:
        # bigserial is monotonic, so the id is a sound cursor here.
        stmt = stmt.where(AuditLog.id < before_id)

    stmt = stmt.order_by(AuditLog.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = []
    for entry, actor in rows:
        read = AuditEntry.model_validate(entry)
        read.actor_name = actor.full_name if actor else None
        items.append(read)

    return AuditPage(items=items, next_before_id=rows[-1][0].id if has_more and rows else None)
