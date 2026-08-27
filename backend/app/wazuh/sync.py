"""Per-tenant agent sync.

`agents` is a cache, never a source of truth. Everything here is a projection of
what a client's manager said the last time we could reach it, and every consumer
shows `synced_at` so an analyst can tell fresh from stale.

Three rules this module exists to keep:

**A manager outage is not our outage.** A failed sync writes `last_sync_error`
and leaves the previous rows in place. Stale agent data beats an empty page.

**A shared manager is scoped by group.** When `agent_group` is set, that group is
the tenant's boundary and the sync must never read outside it - otherwise one
client's console would list another client's fleet.

**Pruning is scoped to what this sync could see.** Rows are removed only when the
sync succeeded, and only within the tenant being synced. A partial read must
never be mistaken for a decommissioned fleet.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Tenant, WazuhConnection
from app.wazuh.manager_client import ManagerError, WazuhManagerClient

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    tenant_id: uuid.UUID
    ok: bool
    synced: int = 0
    removed: int = 0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def _keepalive(value: object) -> datetime | None:
    """Wazuh reports an agent that has never checked in as 9999-12-31 rather than
    as null. Storing that would put the year 9999 on an analyst's screen."""
    if not isinstance(value, str) or not value or value.startswith("9999"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _ip(value: object) -> str | None:
    """The `ip` column is `inet`; anything the manager cannot express as an
    address is dropped rather than allowed to fail the whole upsert."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _row(tenant_id: uuid.UUID, item: dict, now: datetime) -> dict | None:
    agent_id = item.get("id")
    if not agent_id:
        return None
    os_info = item.get("os") if isinstance(item.get("os"), dict) else {}
    groups = item.get("group")
    return {
        "tenant_id": tenant_id,
        "agent_id": str(agent_id),
        "name": str(item.get("name") or agent_id),
        "ip": _ip(item.get("ip")),
        "os_platform": os_info.get("platform"),
        "os_name": os_info.get("name"),
        "version": item.get("version"),
        "status": item.get("status"),
        "groups": [str(g) for g in groups] if isinstance(groups, list) else [],
        "last_keepalive": _keepalive(item.get("lastKeepAlive")),
        "synced_at": now,
    }


async def sync_tenant(
    session: AsyncSession,
    tenant: Tenant,
    connection: WazuhConnection,
    *,
    transport=None,
) -> SyncResult:
    """Refresh one tenant's agent cache. Commits. Never raises."""
    now = datetime.now(UTC)
    result = SyncResult(tenant_id=tenant.id, ok=False)

    try:
        async with WazuhManagerClient(connection, transport=transport) as client:
            items = await client.agents(group=connection.agent_group)
    except ManagerError as exc:
        result.error = str(exc)
    except Exception as exc:  # noqa: BLE001 - one bad tenant must not stop the sweep
        log.exception("unexpected failure syncing agents for tenant %s", tenant.slug)
        result.error = f"unexpected error: {type(exc).__name__}"

    if result.error is not None:
        connection.last_sync_error = result.error
        await session.commit()
        return result

    rows = [row for row in (_row(tenant.id, item, now) for item in items) if row]

    if rows:
        statement = insert(Agent).values(rows)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "agent_id"],
                set_={
                    column: statement.excluded[column]
                    for column in (
                        "name",
                        "ip",
                        "os_platform",
                        "os_name",
                        "version",
                        "status",
                        "groups",
                        "last_keepalive",
                        "synced_at",
                    )
                },
            )
        )

    # Only reached on a successful read, so an empty `rows` here genuinely means
    # the group is empty - not that we could not see it.
    seen = {row["agent_id"] for row in rows}
    prune = delete(Agent).where(Agent.tenant_id == tenant.id)
    if seen:
        prune = prune.where(Agent.agent_id.notin_(seen))
    result.removed = (await session.execute(prune)).rowcount or 0

    connection.last_sync_at = now
    connection.last_sync_error = None
    await session.commit()

    result.ok = True
    result.synced = len(rows)
    if connection.agent_group and not rows:
        result.warnings.append(
            f"Group '{connection.agent_group}' has no agents on this manager, so no "
            "alerts will be delivered for this client."
        )
    return result


async def sync_all(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    transport=None,
) -> list[SyncResult]:
    """Sweep every active tenant that has a manager connection.

    Suspended and offboarding tenants are skipped: we stop reading a client's
    manager the moment they stop being a client.
    """
    stmt = (
        select(Tenant, WazuhConnection)
        .join(WazuhConnection, WazuhConnection.tenant_id == Tenant.id)
        .where(Tenant.status == "active")
    )
    if tenant_id is not None:
        stmt = stmt.where(Tenant.id == tenant_id)

    results = []
    for tenant, connection in (await session.execute(stmt)).all():
        results.append(await sync_tenant(session, tenant, connection, transport=transport))
    return results


async def misgrouped_agents(session: AsyncSession) -> list[dict]:
    """Agents that appear under more than one tenant on the same manager.

    This is the one cross-tenant leak the ingest path cannot catch. The `<group>`
    filter in a client's `ossec.conf` decides which tenant URL an alert is posted
    to, so an agent in the wrong group produces alerts that are correctly signed,
    correctly tenanted by URL, and attributed to the wrong client.

    Agent IDs are unique within a manager. So the same `agent_id` cached under two
    tenants that share a `base_url` means the groups overlap, and one of those
    tenants is seeing the other's data. It is surfaced rather than swallowed.
    """
    rows = await session.execute(
        select(
            WazuhConnection.base_url,
            Agent.agent_id,
            func.count(distinct(Agent.tenant_id)).label("tenants"),
            func.array_agg(distinct(Tenant.slug)).label("slugs"),
            func.min(Agent.name).label("agent_name"),
        )
        .join(WazuhConnection, WazuhConnection.tenant_id == Agent.tenant_id)
        .join(Tenant, Tenant.id == Agent.tenant_id)
        .group_by(WazuhConnection.base_url, Agent.agent_id)
        .having(func.count(distinct(Agent.tenant_id)) > 1)
    )
    return [
        {
            "base_url": base_url,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "tenant_slugs": sorted(slugs),
        }
        for base_url, agent_id, _tenants, slugs, agent_name in rows.all()
    ]
