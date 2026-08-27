"""Monthly partition lifecycle for `alerts`, in plain DDL.

Coolify's managed Postgres image is not guaranteed to ship `pg_partman`, and the
whole job is thirty lines of DDL with one less dependency. Run daily from the
worker, never from cron on the host - Coolify hosts get rebuilt.
"""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

log = logging.getLogger(__name__)

PARENT = "alerts"


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    return date(d.year + month_index // 12, month_index % 12 + 1, 1)


def partition_name(start: date) -> str:
    return f"{PARENT}_{start:%Y_%m}"


async def ensure_partitions(session: AsyncSession, *, today: date | None = None) -> list[str]:
    """Create this month's partition and the next `premake_months`."""
    today = today or datetime.now(UTC).date()
    created: list[str] = []
    for offset in range(settings.partition_premake_months + 1):
        start = add_months(month_start(today), offset)
        end = add_months(start, 1)
        name = partition_name(start)
        await session.execute(
            text(
                f"create table if not exists {name} partition of {PARENT} "
                f"for values from ('{start}') to ('{end}')"
            )
        )
        created.append(name)
    await session.commit()
    return created


async def drop_expired_partitions(session: AsyncSession, *, today: date | None = None) -> list[str]:
    """Drop partitions wholly older than the retention window.

    A partition is dropped only once its upper bound has passed the cutoff, so no
    row inside retention is ever taken with it.
    """
    today = today or datetime.now(UTC).date()
    cutoff = month_start(today - timedelta(days=settings.alert_retention_days))
    rows = await session.execute(
        text(
            "select c.relname from pg_class c "
            "join pg_inherits i on i.inhrelid = c.oid "
            "join pg_class p on p.oid = i.inhparent "
            "where p.relname = :parent"
        ),
        {"parent": PARENT},
    )
    dropped: list[str] = []
    for (name,) in rows:
        try:
            year, month = int(name[-7:-3]), int(name[-2:])
        except ValueError:
            log.warning("skipping unrecognised partition name %s", name)
            continue
        if add_months(date(year, month, 1), 1) <= cutoff:
            await session.execute(text(f"drop table if exists {name}"))
            dropped.append(name)
    await session.commit()
    if dropped:
        log.info("dropped expired alert partitions: %s", ", ".join(dropped))
    return dropped


async def maintain(session: AsyncSession) -> dict[str, list[str]]:
    return {
        "ensured": await ensure_partitions(session),
        "dropped": await drop_expired_partitions(session),
    }
