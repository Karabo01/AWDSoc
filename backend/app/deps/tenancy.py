import uuid

from fastapi import HTTPException, status
from sqlalchemy.sql import ColumnElement

from app.deps.auth import Claims


class TenantScope:
    """The tenant filter for one request, derived from the token alone.

    `tenant_id is None` only ever means a staff fleet view. Client tokens always
    resolve to exactly one tenant.
    """

    def __init__(self, claims) -> None:
        self.is_staff = claims.is_staff
        self.tenant_id: uuid.UUID | None = claims.scope_tenant_id
        if not self.is_staff and self.tenant_id is None:
            # The users table check constraint makes this unreachable; fail loudly
            # rather than silently widening a client to a fleet view.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="No tenant on this session."
            )

    @property
    def is_fleet_view(self) -> bool:
        return self.tenant_id is None

    def apply(self, stmt, column: ColumnElement):
        """Filter a select by this request's tenant. Fleet views are unfiltered
        here and narrowed by the caller's accessible-tenant list instead."""
        if self.tenant_id is not None:
            return stmt.where(column == self.tenant_id)
        return stmt

    def owns(self, tenant_id: uuid.UUID) -> bool:
        return self.is_fleet_view or tenant_id == self.tenant_id


def get_tenant_scope(claims: Claims) -> TenantScope:
    return TenantScope(claims)
