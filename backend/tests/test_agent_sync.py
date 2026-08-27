"""Agent sync: pagination, group scoping, and the shape of a failure.

The database-touching half of `sync_tenant` is not exercised here - there is no
Postgres in this suite - so these cover the parts that are pure: the client's
paging loop, the group parameter that keeps one client out of another's fleet,
and the row mapping that turns a manager's JSON into columns.
"""

import httpx
import pytest

from app.crypto import encrypt
from app.models import WazuhConnection
from app.wazuh.manager_client import MAX_AGENTS, ManagerError, WazuhManagerClient
from app.wazuh.sync import _keepalive, _row


def connection(*, agent_group: str | None = None) -> WazuhConnection:
    blob, version = encrypt("s3cret")
    return WazuhConnection(
        tenant_id=None,
        base_url="https://wazuh.acme.co.za",
        username="awdtech-ro",
        password_enc=blob,
        key_version=version,
        verify_ssl=True,
        agent_group=agent_group,
    )


def manager(pages: list[list[dict]], *, total: int | None = None, seen: list | None = None):
    """A manager that serves `pages` in order and records the params it was asked for."""
    served = {"index": 0}
    reported = sum(len(p) for p in pages) if total is None else total

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/security/user/authenticate"):
            return httpx.Response(200, json={"data": {"token": "t"}})
        if request.url.path.endswith("/agents"):
            if seen is not None:
                seen.append(dict(request.url.params))
            index = served["index"]
            served["index"] += 1
            items = pages[index] if index < len(pages) else []
            return httpx.Response(
                200,
                json={"data": {"affected_items": items, "total_affected_items": reported}},
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def agents(count: int, start: int = 0) -> list[dict]:
    return [
        {
            "id": f"{i:03d}",
            "name": f"host-{i}",
            "ip": "10.0.0.1",
            "os": {"platform": "ubuntu", "name": "Ubuntu 22.04"},
            "version": "Wazuh v4.9.0",
            "status": "active",
            "group": ["default"],
            "lastKeepAlive": "2026-08-26T10:00:00Z",
        }
        for i in range(start, start + count)
    ]


async def test_every_page_is_collected():
    transport = manager([agents(500), agents(120, start=500)])
    async with WazuhManagerClient(connection(), transport=transport) as client:
        result = await client.agents()
    assert len(result) == 620


async def test_the_group_is_sent_on_every_page():
    """On a shared manager the group is the tenant boundary. Dropping it on the
    second page would quietly pull in another client's agents."""
    seen: list[dict] = []
    transport = manager([agents(500), agents(10, start=500)], seen=seen)
    async with WazuhManagerClient(connection(agent_group="acme"), transport=transport) as client:
        await client.agents(group="acme")

    assert len(seen) == 2
    assert all(params.get("group") == "acme" for params in seen)


async def test_a_manager_that_overstates_its_total_does_not_spin_forever():
    """The loop exits on an empty page as well as on the count, because a total
    the manager will not actually serve would otherwise never be reached."""
    transport = manager([agents(3)], total=9_999)
    async with WazuhManagerClient(connection(), transport=transport) as client:
        result = await client.agents()
    assert len(result) == 3


async def test_the_agent_ceiling_is_enforced():
    pages = [agents(500, start=i * 500) for i in range(30)]
    transport = manager(pages, total=15_000)
    async with WazuhManagerClient(connection(), transport=transport) as client:
        result = await client.agents()
    assert len(result) == MAX_AGENTS


async def test_an_unreachable_manager_raises_rather_than_returning_empty():
    """An empty list and a failed read must not be confusable: the caller prunes
    rows the sync did not see, so a silent empty would delete the whole fleet."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/security/user/authenticate"):
            return httpx.Response(200, json={"data": {"token": "t"}})
        return httpx.Response(500)

    async with WazuhManagerClient(
        connection(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ManagerError):
            await client.agents()


def test_a_never_connected_agent_has_no_keepalive():
    """Wazuh uses 9999-12-31 rather than null. Storing it would put the year 9999
    on an analyst's screen and sort that agent to the top of every list."""
    assert _keepalive("9999-12-31T23:59:59Z") is None
    assert _keepalive(None) is None
    assert _keepalive("not a date") is None
    assert _keepalive("2026-08-26T10:00:00Z") is not None


def test_the_row_mapping_survives_a_sparse_agent():
    """A pending agent has almost no fields. The mapping must still produce a row
    rather than throwing and taking the whole tenant's sync with it."""
    import uuid
    from datetime import UTC, datetime

    row = _row(uuid.uuid4(), {"id": "007"}, datetime.now(UTC))
    assert row is not None
    assert row["agent_id"] == "007"
    assert row["name"] == "007"  # falls back to the id rather than being null
    assert row["groups"] == []
    assert row["ip"] is None


def test_an_agent_with_no_id_is_dropped():
    """`agent_id` is half the primary key; a row without one cannot be stored."""
    import uuid
    from datetime import UTC, datetime

    assert _row(uuid.uuid4(), {"name": "nameless"}, datetime.now(UTC)) is None
