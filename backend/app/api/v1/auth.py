import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps.auth import Claims, CurrentUser, accessible_tenant_ids
from app.models import Tenant, User
from app.redis_client import is_revoked, revoke_token
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    RefreshRequest,
    SwitchTenantRequest,
    TenantSummary,
    TokenPair,
)
from app.security import (
    TokenError,
    decode_token,
    hash_password,
    issue_access_token,
    issue_refresh_token,
    needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]

INVALID_LOGIN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect."
)
# Cost-matched to a real argon2id verify so a miss and a wrong password take
# comparable time and the login form cannot enumerate accounts.
_DUMMY_HASH = hash_password("account-enumeration-is-not-a-feature")


def _issue_pair(user: User, active_tenant: uuid.UUID | None) -> TokenPair:
    access, expires_at = issue_access_token(
        user_id=user.id,
        role=user.role,
        is_staff=user.is_staff,
        tenant_id=user.tenant_id,
        active_tenant=active_tenant,
    )
    refresh, _, _ = issue_refresh_token(
        user_id=user.id,
        role=user.role,
        is_staff=user.is_staff,
        tenant_id=user.tenant_id,
        active_tenant=active_tenant,
    )
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=expires_at)


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, session: Session) -> TokenPair:
    user = await session.scalar(select(User).where(User.email == payload.email))
    if user is None or not user.is_active:
        verify_password(payload.password, _DUMMY_HASH)
        raise INVALID_LOGIN
    if not verify_password(payload.password, user.password_hash):
        raise INVALID_LOGIN

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.last_login_at = datetime.now(UTC)
    await session.commit()

    # Staff start in the all-clients view; that is the working surface.
    return _issue_pair(user, active_tenant=None)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: Session) -> TokenPair:
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    if await is_revoked(claims.jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="This session has been signed out."
        )

    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="This account is no longer active."
        )

    # Rotate: the presented refresh token is spent.
    await revoke_token(claims.jti, claims.expires_at)
    active = claims.active_tenant if user.is_staff else None
    if active is not None and not await _may_access(session, user, active):
        active = None
    return _issue_pair(user, active_tenant=active)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest) -> None:
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except TokenError:
        # Signing out with a token we cannot read is still signed out.
        return
    await revoke_token(claims.jti, claims.expires_at)


async def _may_access(session: AsyncSession, user: User, tenant_id: uuid.UUID) -> bool:
    allowed = await accessible_tenant_ids(session, user)
    return allowed is None or tenant_id in allowed


async def _visible_tenants(session: AsyncSession, user: User) -> list[Tenant]:
    if not user.is_staff:
        return []
    allowed = await accessible_tenant_ids(session, user)
    stmt = select(Tenant).order_by(Tenant.name)
    if allowed is not None:
        stmt = stmt.where(Tenant.id.in_(allowed))
    return list(await session.scalars(stmt))


@router.get("/me", response_model=CurrentUserResponse)
async def me(
    user: CurrentUser,
    session: Session,
    claims: Claims,
) -> CurrentUserResponse:
    tenants = await _visible_tenants(session, user)
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_staff=user.is_staff,
        tenant_id=user.tenant_id,
        active_tenant=claims.active_tenant,
        tenants=[TenantSummary.model_validate(t) for t in tenants],
    )


@router.post("/switch-tenant", response_model=TokenPair)
async def switch_tenant(
    payload: SwitchTenantRequest, user: CurrentUser, session: Session
) -> TokenPair:
    if not user.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only AWDTECH staff can switch clients.",
        )
    if payload.tenant_id is not None:
        tenant = await session.get(Tenant, payload.tenant_id)
        if tenant is None or not await _may_access(session, user, payload.tenant_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No such client."
            )
    return _issue_pair(user, active_tenant=payload.tenant_id)
