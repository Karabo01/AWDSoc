"""Audit trail.

Every state change worth arguing about later goes through here. On an MSSP that
now includes SLA pauses, because a paused clock cannot breach.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record(
    session: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append to the audit log. Never commits - it joins the caller's transaction
    so an audited change and its record land together or not at all."""
    session.add(
        AuditLog(
            action=action,
            target_type=target_type,
            target_id=target_id,
            tenant_id=tenant_id,
            user_id=user_id,
            detail=detail or {},
        )
    )
