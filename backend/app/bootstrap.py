"""First-run administrator, created from the environment.

A fresh deployment has no users, and creating the first one needed a shell in the
container. That is a bad dependency: web terminals are the flakiest part of most
platforms, and it makes a deployment non-reproducible.

Safety comes from one rule: **this only ever runs when the users table is empty.**
It cannot change an existing account, cannot re-grant a revoked one, and turns
into a no-op the moment anybody exists.
"""

import logging
import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import User
from app.security import hash_password

log = logging.getLogger(__name__)

MIN_PASSWORD = 12


async def ensure_bootstrap_admin(session: AsyncSession) -> str | None:
    """Create the first platform_admin if there are no users at all.

    Returns the email created, or None if nothing was done.
    """
    email = (settings.bootstrap_admin_email or "").strip()
    if not email:
        return None

    existing = await session.scalar(select(func.count()).select_from(User))
    if existing:
        # Deliberately loud: a password sitting in the environment after setup is
        # a standing risk, and nothing here will ever consume it again.
        log.warning(
            "BOOTSTRAP_ADMIN_EMAIL is set but %s user(s) already exist; "
            "nothing was created. Remove the BOOTSTRAP_ADMIN_* variables.",
            existing,
        )
        return None

    password = settings.bootstrap_admin_password or ""
    generated = False
    if len(password) < MIN_PASSWORD:
        if password:
            log.warning(
                "BOOTSTRAP_ADMIN_PASSWORD is shorter than %s characters; generating one instead",
                MIN_PASSWORD,
            )
        password = secrets.token_urlsafe(18)
        generated = True

    session.add(
        User(
            email=email,
            full_name=settings.bootstrap_admin_name or "Platform Admin",
            role="platform_admin",
            is_staff=True,
            tenant_id=None,
            password_hash=hash_password(password),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # Two api replicas booting together. One wins; that is fine.
        await session.rollback()
        return None

    log.warning("created bootstrap administrator %s", email)
    if generated:
        # The only place this is ever readable. Coolify shows it in the resource
        # logs; sign in, change it, and remove the variables.
        log.warning("bootstrap password for %s: %s", email, password)
    return email


async def run_bootstrap() -> None:
    """Startup hook. Never prevents the API from booting.

    A degraded Postgres must not stop the process from starting - ingest still
    needs to buffer, and health reports the problem accurately.
    """
    if not settings.bootstrap_admin_email:
        return
    try:
        async with SessionLocal() as session:
            await ensure_bootstrap_admin(session)
    except Exception as exc:  # noqa: BLE001 - boot must survive any database problem
        if "does not exist" in str(exc):
            # Overwhelmingly the cause: the pre-deploy migration never ran.
            log.error(
                "bootstrap administrator skipped: the schema is missing. "
                "Run `alembic upgrade head`, and set it as the pre-deploy "
                "command on the api resource so it applies on every deploy."
            )
        else:
            log.exception("bootstrap administrator could not be created")
