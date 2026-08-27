"""check_connection is the M2 acceptance surface: it decides whether onboarding
worked. It must always produce a verdict and never raise."""

import httpx
import pytest

from app.crypto import encrypt
from app.models import WazuhConnection
from app.wazuh.manager_client import check_connection


def connection(*, agent_group: str | None = None, password: str = "s3cret") -> WazuhConnection:
    blob, version = encrypt(password)
    return WazuhConnection(
        tenant_id=None,
        base_url="https://wazuh.acme.co.za",
        username="awdtech-ro",
        password_enc=blob,
        key_version=version,
        verify_ssl=True,
        agent_group=agent_group,
    )


def manager(
    *,
    auth_status: int = 200,
    groups_total: int = 1,
    agents_total: int = 12,
    group_agents_total: int = 5,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/security/user/authenticate"):
            if auth_status != 200:
                return httpx.Response(auth_status, json={"title": "nope"})
            return httpx.Response(200, json={"data": {"token": "a-manager-token"}})
        if path.endswith("/manager/info"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "affected_items": [{"version": "v4.9.0", "node_name": "node01"}]
                    }
                },
            )
        if path.endswith("/groups"):
            return httpx.Response(200, json={"data": {"total_affected_items": groups_total}})
        if path.endswith("/agents"):
            total = group_agents_total if "group" in request.url.params else agents_total
            return httpx.Response(200, json={"data": {"total_affected_items": total}})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


async def test_a_healthy_dedicated_manager_reports_version_and_agents():
    result = await check_connection(connection(), transport=manager())
    assert result.ok
    assert result.manager_version == "v4.9.0"
    assert result.node_name == "node01"
    assert result.agent_count == 12
    assert result.error is None


async def test_bad_credentials_are_reported_not_raised():
    result = await check_connection(connection(), transport=manager(auth_status=401))
    assert not result.ok
    assert "rejected these credentials" in result.error


async def test_an_unreachable_manager_is_reported_not_raised():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    result = await check_connection(connection(), transport=httpx.MockTransport(refuse))
    assert not result.ok
    assert "could not reach the manager" in result.error


async def test_a_shared_manager_confirms_the_tenant_group_exists():
    result = await check_connection(
        connection(agent_group="acme-corp"), transport=manager()
    )
    assert result.ok
    assert result.agent_group == "acme-corp"
    assert result.agent_group_exists is True
    assert result.agent_group_count == 5


async def test_a_missing_agent_group_fails_the_check_outright():
    """On a shared manager the group filter is the only thing routing this
    tenant's alerts. A missing group silently filters them to nothing, so this is
    an error rather than a warning."""
    result = await check_connection(
        connection(agent_group="acme-corp"), transport=manager(groups_total=0)
    )
    assert not result.ok
    assert "does not exist on this manager" in result.error


async def test_an_empty_agent_group_warns_but_passes():
    result = await check_connection(
        connection(agent_group="acme-corp"), transport=manager(group_agents_total=0)
    )
    assert result.ok
    assert any("has no agents" in w for w in result.warnings)


async def test_a_manager_with_no_agents_warns():
    result = await check_connection(connection(), transport=manager(agents_total=0))
    assert result.ok
    assert any("no agents enrolled" in w for w in result.warnings)


async def test_an_undecryptable_credential_is_our_fault_not_the_network():
    conn = connection()
    conn.key_version = 99  # no key material for this version
    result = await check_connection(conn, transport=manager())
    assert not result.ok
    assert "cannot be decrypted" in result.error


async def test_the_password_never_appears_in_the_result():
    result = await check_connection(
        connection(password="hunter2-the-real-one", agent_group="acme-corp"),
        transport=manager(groups_total=0),
    )
    assert "hunter2" not in repr(result)


@pytest.mark.parametrize("status", [500, 502, 403])
async def test_any_manager_error_still_yields_a_verdict(status):
    result = await check_connection(connection(), transport=manager(auth_status=status))
    assert result.ok is False
    assert result.error
