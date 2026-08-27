"""User administration.

Two audiences with different powers over different sets:

* `platform_admin` manages everyone, staff included.
* `client_admin` manages **their own tenant's** users only, and can only ever
  create client roles. A client admin who could mint a `soc_analyst` would have
  granted themselves cross-tenant read, so that path does not exist rather than
  being guarded by a check somebody could later move.

Nobody may change their own role or deactivate themselves. Both are how an
estate ends up with no administrator at all, and both are trivial to hit by
accident on a page listing every user including yourself.
"""

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_session
from app.deps.rbac import require_roles
from app.models import Tenant, User
from app.models.user import CLIENT_ROLES, STAFF_ROLES
from app.schemas.user import UserCreate, UserCreated, UserRead, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])

Session = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[User, Depends(require_roles("platform_admin", "client_admin"))]

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user.")
GENERATED_PASSWORD_BYTES = 18


def _read(user: User, tenant: Tenant | None) -> UserRead:
    payload = UserRead.model_validate(user)
    if tenant is not None:
        payload.tenant_name = tenant.name
    return payload


def _guard_target(actor: User, target: User) -> None:
    """A client_admin may only ever act inside their own tenant.

    The 404 is deliberate and matches every other cross-tenant read in the
    console: a 403 would confirm that the id exists somewhere else.
    """
    if actor.role == "platform_admin":
        return
    if target.tenant_id != actor.tenant_id or target.is_staff:
        raise NOT_FOUND


@router.get("", response_model=list[UserRead])
async def list_users(
    actor: Admin,
    session: Session,
    include_inactive: Annotated[bool, Query()] = False,
) -> list[UserRead]:
    stmt = (
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id, isouter=True)
        .order_by(User.full_name)
    )
    if actor.role != "platform_admin":
        stmt = stmt.where(User.tenant_id == actor.tenant_id, User.is_staff.is_(False))
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))

    return [_read(user, tenant) for user, tenant in (await session.execute(stmt)).all()]


@router.post("", response_model=UserCreated, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, actor: Admin, session: Session) -> UserCreated:
    is_staff = payload.role in STAFF_ROLES

    if actor.role != "platform_admin":
        if payload.role not in CLIENT_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only create client users.",
            )
        # Ignore whatever tenant the body named; a client admin has exactly one.
        tenant_id = actor.tenant_id
    else:
        tenant_id = payload.tenant_id

    if is_staff and tenant_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Staff roles are not scoped to a client. Leave tenant_id empty.",
        )
    if not is_staff and tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A client role needs a tenant_id.",
        )

    tenant = None
    if tenant_id is not None:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No such client.")

    generated = payload.password is None
    password = payload.password or secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)

    user = User(
        email=str(payload.email),
        full_name=payload.full_name,
        role=payload.role,
        is_staff=is_staff,
        tenant_id=tenant_id,
        password_hash=hash_password(password),
    )
    session.add(user)

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        # `email` is citext-unique, so this is the duplicate case.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email address already has an account.",
        ) from exc

    await audit.record(
        session,
        action="user.created",
        target_type="user",
        target_id=user.id,
        tenant_id=tenant_id,
        user_id=actor.id,
        detail={"email": user.email, "role": user.role},
    )
    await session.commit()

    # Returned once. There is no route that reads it back.
    return UserCreated(user=_read(user, tenant), password=password if generated else None)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID, payload: UserUpdate, actor: Admin, session: Session
) -> UserRead:
    target = await session.get(User, user_id)
    if target is None:
        raise NOT_FOUND
    _guard_target(actor, target)

    changes: dict = {}

    if payload.role is not None and payload.role != target.role:
        if target.id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot change your own role.",
            )
        # Changing role across the staff boundary would break the tenancy check
        # constraint on `users`, and is not something an edit form should do
        # silently. Delete and recreate is the honest path.
        if (payload.role in STAFF_ROLES) != target.is_staff:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user cannot move between staff and client roles. "
                "Deactivate this account and create the right one.",
            )
        if actor.role != "platform_admin" and payload.role not in CLIENT_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only assign client roles.",
            )
        changes["role"] = {"from": target.role, "to": payload.role}
        target.role = payload.role

    if payload.is_active is not None and payload.is_active != target.is_active:
        if target.id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account.",
            )
        changes["is_active"] = payload.is_active
        target.is_active = payload.is_active

    if payload.full_name is not None and payload.full_name != target.full_name:
        changes["full_name"] = payload.full_name
        target.full_name = payload.full_name

    if changes:
        await audit.record(
            session,
            action="user.updated",
            target_type="user",
            target_id=target.id,
            tenant_id=target.tenant_id,
            user_id=actor.id,
            detail=changes,
        )
        await session.commit()

    tenant = await session.get(Tenant, target.tenant_id) if target.tenant_id else None
    return _read(target, tenant)


@router.post("/{user_id}/reset-password", response_model=UserCreated)
async def reset_password(user_id: uuid.UUID, actor: Admin, session: Session) -> UserCreated:
    """Issue a new password and return it once.

    Existing sessions are left alone on purpose. Revoking them belongs to
    deactivation, which is the action for "this person should not be here"; a
    reset is usually "they forgot it", and cutting their colleague off mid-triage
    is not part of that.
    """
    target = await session.get(User, user_id)
    if target is None:
        raise NOT_FOUND
    _guard_target(actor, target)

    password = secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)
    target.password_hash = hash_password(password)

    await audit.record(
        session,
        action="user.password_reset",
        target_type="user",
        target_id=target.id,
        tenant_id=target.tenant_id,
        user_id=actor.id,
        detail={"email": target.email},
    )
    await session.commit()

    tenant = await session.get(Tenant, target.tenant_id) if target.tenant_id else None
    return UserCreated(user=_read(target, tenant), password=password)
