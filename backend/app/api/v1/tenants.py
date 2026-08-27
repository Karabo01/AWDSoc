"""Tenant onboarding. platform_admin only, throughout.

The success criterion for this milestone: onboarding a client is a form here plus
one command on their manager. Everything the manager needs is generated from the
tenant row and handed back once, at creation.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import audit
from app.crypto import encrypt
from app.db import get_session
from app.deps.auth import CurrentUser
from app.deps.rbac import require_roles
from app.ingest.auth import tenant_cache
from app.models import Tenant, TenantSla, WazuhConnection
from app.schemas.tenant import (
    ConnectionCheckResult,
    SlaBand,
    SlaPolicy,
    TenantCreate,
    TenantRead,
    TenantSecretRevealed,
    TenantUpdate,
)
from app.wazuh.manager_client import check_connection
from app.wazuh.onboarding import (
    generate_ingest_secret,
    ingest_url,
    install_command,
    integration_block,
    pick_colour,
)

router = APIRouter(
    prefix="/tenants",
    tags=["tenants"],
    dependencies=[Depends(require_roles("platform_admin"))],
)

Session = Annotated[AsyncSession, Depends(get_session)]

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such client.")


async def _load(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).options(selectinload(Tenant.connection))
    )
    if tenant is None:
        raise NOT_FOUND
    return tenant


async def _sla_policy(session: AsyncSession, tenant_id: uuid.UUID) -> SlaPolicy:
    rows = await session.scalars(
        select(TenantSla).where(TenantSla.tenant_id == tenant_id).order_by(TenantSla.severity_min)
    )
    return SlaPolicy(
        bands=[
            SlaBand(
                severity_min=row.severity_min,
                respond_minutes=row.respond_minutes,
                resolve_minutes=row.resolve_minutes,
            )
            for row in rows
        ]
    )


async def _read(session: AsyncSession, tenant: Tenant) -> TenantRead:
    payload = TenantRead.model_validate(tenant)
    payload.sla = await _sla_policy(session, tenant.id)
    return payload


async def _replace_sla(session: AsyncSession, tenant_id: uuid.UUID, policy: SlaPolicy) -> None:
    await session.execute(delete(TenantSla).where(TenantSla.tenant_id == tenant_id))
    for band in policy.bands:
        session.add(
            TenantSla(
                tenant_id=tenant_id,
                severity_min=band.severity_min,
                respond_minutes=band.respond_minutes,
                resolve_minutes=band.resolve_minutes,
            )
        )


@router.get("", response_model=list[TenantRead])
async def list_tenants(session: Session) -> list[TenantRead]:
    tenants = await session.scalars(
        select(Tenant).options(selectinload(Tenant.connection)).order_by(Tenant.name)
    )
    return [await _read(session, tenant) for tenant in tenants]


@router.get("/{tenant_id}", response_model=TenantRead)
async def get_tenant(tenant_id: uuid.UUID, session: Session) -> TenantRead:
    return await _read(session, await _load(session, tenant_id))


@router.post("", response_model=TenantSecretRevealed, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate, user: CurrentUser, session: Session
) -> TenantSecretRevealed:
    secret = generate_ingest_secret()

    if payload.colour is None:
        taken = list(await session.scalars(select(Tenant.colour)))
        payload.colour = pick_colour(taken)

    tenant = Tenant(
        slug=payload.slug,
        name=payload.name,
        alert_floor=payload.alert_floor,
        grouping_window_minutes=payload.grouping_window_minutes,
        ingest_cidrs=payload.ingest_cidrs,
        colour=payload.colour,
        ingest_secret=secret,
    )
    session.add(tenant)

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The slug {payload.slug!r} is already in use.",
        ) from exc

    if payload.connection:
        password_enc, key_version = encrypt(payload.connection.password)
        session.add(
            WazuhConnection(
                tenant_id=tenant.id,
                base_url=payload.connection.base_url,
                username=payload.connection.username,
                password_enc=password_enc,
                key_version=key_version,
                verify_ssl=payload.connection.verify_ssl,
                agent_group=payload.connection.agent_group,
            )
        )

    if payload.sla:
        await _replace_sla(session, tenant.id, payload.sla)

    await audit.record(
        session,
        action="tenant.created",
        target_type="tenant",
        target_id=tenant.id,
        tenant_id=tenant.id,
        user_id=user.id,
        detail={"slug": tenant.slug, "name": tenant.name},
    )
    await session.commit()

    tenant = await _load(session, tenant.id)
    group = tenant.connection.agent_group if tenant.connection else None
    return TenantSecretRevealed(
        tenant=await _read(session, tenant),
        ingest_secret=secret,
        ingest_url=ingest_url(tenant.slug),
        integration_block=integration_block(
            tenant.slug, secret, alert_floor=tenant.alert_floor, group=group
        ),
        install_command=install_command(
            tenant.slug, secret, alert_floor=tenant.alert_floor, group=group
        ),
    )


@router.patch("/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    tenant_id: uuid.UUID, payload: TenantUpdate, user: CurrentUser, session: Session
) -> TenantRead:
    tenant = await _load(session, tenant_id)
    changed: dict[str, object] = {}

    for field in ("name", "status", "alert_floor", "grouping_window_minutes", "colour"):
        value = getattr(payload, field)
        if value is not None and value != getattr(tenant, field):
            changed[field] = value
            setattr(tenant, field, value)

    if payload.ingest_cidrs is not None:
        changed["ingest_cidrs"] = payload.ingest_cidrs
        tenant.ingest_cidrs = payload.ingest_cidrs

    if payload.connection is not None:
        connection = tenant.connection
        if connection is None:
            if not (
                payload.connection.base_url
                and payload.connection.username
                and payload.connection.password
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A first connection needs base_url, username and password.",
                )
            password_enc, key_version = encrypt(payload.connection.password)
            connection = WazuhConnection(
                tenant_id=tenant.id,
                base_url=payload.connection.base_url,
                username=payload.connection.username,
                password_enc=password_enc,
                key_version=key_version,
                verify_ssl=(
                    True if payload.connection.verify_ssl is None else payload.connection.verify_ssl
                ),
                agent_group=payload.connection.agent_group,
            )
            session.add(connection)
            changed["connection"] = "created"
        else:
            for field in ("base_url", "username", "verify_ssl", "agent_group"):
                value = getattr(payload.connection, field)
                if value is not None:
                    setattr(connection, field, value)
            if payload.connection.password is not None:
                # Re-encrypting also re-stamps key_version, which is how a key
                # rotation gets applied without a migration.
                connection.password_enc, connection.key_version = encrypt(
                    payload.connection.password
                )
                changed["connection_password"] = "rotated"
            changed.setdefault("connection", "updated")

    await audit.record(
        session,
        action="tenant.updated",
        target_type="tenant",
        target_id=tenant.id,
        tenant_id=tenant.id,
        user_id=user.id,
        # Values, never credentials: the password only ever appears as "rotated".
        detail=changed,
    )
    tenant_cache.invalidate(tenant.slug)
    await session.commit()
    return await _read(session, await _load(session, tenant_id))


@router.post("/{tenant_id}/rotate-secret", response_model=TenantSecretRevealed)
async def rotate_secret(
    tenant_id: uuid.UUID, user: CurrentUser, session: Session
) -> TenantSecretRevealed:
    """Returns the new secret once. There is no way to read it back.

    The old secret stops working immediately, so the client's manager will fail
    to deliver until the new block is installed. That is deliberate - a rotation
    that leaves the old key valid is not a rotation.
    """
    tenant = await _load(session, tenant_id)
    secret = generate_ingest_secret()
    tenant.ingest_secret = secret

    await audit.record(
        session,
        action="tenant.secret_rotated",
        target_type="tenant",
        target_id=tenant.id,
        tenant_id=tenant.id,
        user_id=user.id,
    )
    # This process only. Other replicas pick the new secret up within
    # tenant_cache_soft_ttl, which is immaterial: rotation already breaks
    # delivery until the client's manager is reinstalled.
    tenant_cache.invalidate(tenant.slug)
    await session.commit()

    group = tenant.connection.agent_group if tenant.connection else None
    return TenantSecretRevealed(
        tenant=await _read(session, tenant),
        ingest_secret=secret,
        ingest_url=ingest_url(tenant.slug),
        integration_block=integration_block(
            tenant.slug, secret, alert_floor=tenant.alert_floor, group=group
        ),
        install_command=install_command(
            tenant.slug, secret, alert_floor=tenant.alert_floor, group=group
        ),
    )


@router.post("/{tenant_id}/test-connection", response_model=ConnectionCheckResult)
async def test_connection(tenant_id: uuid.UUID, session: Session) -> ConnectionCheckResult:
    tenant = await _load(session, tenant_id)
    if tenant.connection is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This client has no Wazuh connection configured yet.",
        )
    result = await check_connection(tenant.connection)
    return ConnectionCheckResult(**vars(result))


@router.get("/{tenant_id}/sla", response_model=SlaPolicy)
async def get_sla(tenant_id: uuid.UUID, session: Session) -> SlaPolicy:
    await _load(session, tenant_id)
    return await _sla_policy(session, tenant_id)


@router.put("/{tenant_id}/sla", response_model=SlaPolicy)
async def put_sla(
    tenant_id: uuid.UUID, policy: SlaPolicy, user: CurrentUser, session: Session
) -> SlaPolicy:
    """Replaces the whole policy. Existing incidents keep the deadlines they were
    given - a contract change does not retroactively breach open cases."""
    await _load(session, tenant_id)
    await _replace_sla(session, tenant_id, policy)
    await audit.record(
        session,
        action="tenant.sla_updated",
        target_type="tenant",
        target_id=tenant_id,
        tenant_id=tenant_id,
        user_id=user.id,
        detail={"bands": [band.model_dump() for band in policy.bands]},
    )
    await session.commit()
    return await _sla_policy(session, tenant_id)
