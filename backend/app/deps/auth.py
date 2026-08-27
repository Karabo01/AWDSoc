import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import StaffTenantAccess, User
from app.security import TokenClaims, TokenError, decode_token

bearer = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> TokenClaims:
    if credentials is None:
        raise CREDENTIALS_ERROR
    try:
        return decode_token(credentials.credentials, "access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    claims: Annotated[TokenClaims, Depends(get_claims)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise CREDENTIALS_ERROR
    # A role or tenancy change must not be honoured until the token is reissued.
    if user.role != claims.role or user.is_staff != claims.is_staff:
        raise CREDENTIALS_ERROR
    if not user.is_staff and user.tenant_id != claims.tenant_id:
        raise CREDENTIALS_ERROR
    return user


async def accessible_tenant_ids(session: AsyncSession, user: User) -> list[uuid.UUID] | None:
    """Tenants a staff user may see. None means every tenant.

    Client users are handled by their fixed token tenant and never reach here.
    """
    if not user.is_staff:
        return [user.tenant_id] if user.tenant_id else []
    rows = await session.scalars(
        select(StaffTenantAccess.tenant_id).where(StaffTenantAccess.user_id == user.id)
    )
    ids = list(rows)
    return ids or None


CurrentUser = Annotated[User, Depends(get_current_user)]
Claims = Annotated[TokenClaims, Depends(get_claims)]
