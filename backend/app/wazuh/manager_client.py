"""Read-only client for a tenant's Wazuh Manager API.

The console never writes to Wazuh. This client authenticates, reads, and caches;
nothing here mutates a client's manager.

**This is the only place a tenant password is decrypted.** Never in a serialiser,
never in a route handler, never in a log line.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.crypto import EncryptionError, decrypt
from app.models import WazuhConnection

log = logging.getLogger(__name__)

# A client's manager being slow must never become our outage. Every call is
# cached and every consumer tolerates staleness, so failing fast is correct.
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# The manager's own default page size is 500. A ceiling on the total keeps one
# misconfigured tenant - a group holding the whole fleet - from turning a sync
# into an unbounded read.
AGENT_PAGE = 500
MAX_AGENTS = 10_000


class ManagerError(Exception):
    """Any failure reaching or authenticating to a tenant's manager."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class ConnectionCheck:
    ok: bool
    error: str | None = None
    manager_version: str | None = None
    node_name: str | None = None
    agent_count: int | None = None
    # Shared-manager onboarding: does the tenant's agent group actually exist,
    # and how many agents are in it?
    agent_group: str | None = None
    agent_group_exists: bool | None = None
    agent_group_count: int | None = None
    warnings: list[str] = field(default_factory=list)


class WazuhManagerClient:
    def __init__(
        self, connection: WazuhConnection, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._base_url = connection.base_url.rstrip("/")
        self._username = connection.username
        self._password_enc = connection.password_enc
        self._key_version = connection.key_version
        self._verify_ssl = connection.verify_ssl
        self.agent_group = connection.agent_group
        self._transport = transport  # tests only
        self._token: str | None = None

    async def __aenter__(self) -> "WazuhManagerClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            verify=self._verify_ssl,
            timeout=DEFAULT_TIMEOUT,
            transport=self._transport,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def authenticate(self) -> None:
        try:
            password = decrypt(self._password_enc, self._key_version)
        except EncryptionError as exc:
            # A key-version mismatch is our problem, not the client's network.
            raise ManagerError(f"stored credential cannot be decrypted: {exc}") from exc

        try:
            response = await self._client.post(
                "/security/user/authenticate",
                auth=(self._username, password),
            )
        except httpx.HTTPError as exc:
            raise ManagerError(f"could not reach the manager: {type(exc).__name__}") from exc
        finally:
            del password

        if response.status_code == 401:
            raise ManagerError("the manager rejected these credentials", status=401)
        if response.status_code >= 400:
            raise ManagerError(
                f"authentication failed with HTTP {response.status_code}",
                status=response.status_code,
            )

        token = response.json().get("data", {}).get("token")
        if not token:
            raise ManagerError("the manager returned no token")
        self._token = token

    async def _get(self, path: str, **params: Any) -> dict:
        if self._token is None:
            await self.authenticate()
        try:
            response = await self._client.get(
                path,
                params=params or None,
                headers={"Authorization": f"Bearer {self._token}"},
            )
            if response.status_code == 401:
                # Manager tokens are short-lived; one retry, then give up.
                self._token = None
                await self.authenticate()
                response = await self._client.get(
                    path,
                    params=params or None,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
        except httpx.HTTPError as exc:
            raise ManagerError(f"could not reach the manager: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            raise ManagerError(
                f"{path} failed with HTTP {response.status_code}", status=response.status_code
            )
        return response.json()

    async def manager_info(self) -> dict:
        payload = await self._get("/manager/info")
        return payload.get("data", {}).get("affected_items", [{}])[0]

    async def agent_count(self, group: str | None = None) -> int:
        params: dict[str, Any] = {"limit": 1}
        if group:
            params["group"] = group
        payload = await self._get("/agents", **params)
        return int(payload.get("data", {}).get("total_affected_items", 0))

    async def group_exists(self, group: str) -> bool:
        try:
            payload = await self._get("/groups", groups_list=group)
        except ManagerError as exc:
            if exc.status == 404:
                return False
            raise
        return int(payload.get("data", {}).get("total_affected_items", 0)) > 0

    async def agents(self, group: str | None = None) -> list[dict]:
        """Every agent visible to this tenant, paged out of the manager.

        On a shared manager `group` is the tenant's boundary and must be applied
        here - without it one client's sync would cache another client's fleet.
        The caller passes `self.agent_group`; it is a parameter rather than an
        implicit read so a deliberate whole-manager sync stays possible.
        """
        collected: list[dict] = []
        offset = 0
        while True:
            params: dict[str, Any] = {"limit": AGENT_PAGE, "offset": offset}
            if group:
                params["group"] = group
            payload = await self._get("/agents", **params)
            data = payload.get("data", {})
            items = data.get("affected_items") or []
            collected.extend(items)

            total = int(data.get("total_affected_items", len(collected)))
            offset += len(items)
            # `not items` guards a manager that reports a total it will not serve;
            # without it a bad total spins this loop forever.
            if not items or offset >= total or len(collected) >= MAX_AGENTS:
                break
        return collected[:MAX_AGENTS]

    async def rule(self, rule_id: int) -> dict | None:
        """One rule definition. None means the manager does not know it."""
        payload = await self._get("/rules", rule_ids=str(rule_id))
        items = payload.get("data", {}).get("affected_items") or []
        return items[0] if items else None


async def check_connection(
    connection: WazuhConnection, *, transport: httpx.AsyncBaseTransport | None = None
) -> ConnectionCheck:
    """Validate reachability for onboarding. Never raises - the result is the report."""
    try:
        async with WazuhManagerClient(connection, transport=transport) as client:
            await client.authenticate()
            info = await client.manager_info()
            check = ConnectionCheck(
                ok=True,
                manager_version=info.get("version"),
                node_name=info.get("node_name"),
                agent_count=await client.agent_count(),
                agent_group=client.agent_group,
            )

            if client.agent_group:
                check.agent_group_exists = await client.group_exists(client.agent_group)
                if check.agent_group_exists:
                    check.agent_group_count = await client.agent_count(client.agent_group)
                    if check.agent_group_count == 0:
                        check.warnings.append(
                            f"Group '{client.agent_group}' exists but has no agents. "
                            "Alerts will only arrive once agents join it."
                        )
                else:
                    check.ok = False
                    check.error = (
                        f"Group '{client.agent_group}' does not exist on this manager. "
                        "Create it before adding the integration block, or alerts will "
                        "be filtered to nothing."
                    )
            elif check.agent_count == 0:
                check.warnings.append("This manager has no agents enrolled yet.")

            return check
    except ManagerError as exc:
        return ConnectionCheck(ok=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - onboarding must always get a verdict
        log.exception("unexpected failure checking a manager connection")
        return ConnectionCheck(ok=False, error=f"unexpected error: {type(exc).__name__}")
