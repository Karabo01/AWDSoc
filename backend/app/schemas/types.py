"""Shared field types for the API boundary.

asyncpg hands back native Python objects for Postgres network types: an `inet[]`
column arrives as `list[IPv4Address]` and a `cidr[]` as `list[IPv4Network]`.
Pydantic will not coerce those into `list[str]`, so any response model exposing
one raises a ValidationError - at response time, after the transaction has
already committed.

Every network-typed column crossing the API boundary uses `StrList` for that
reason. Writing plain strings back is unaffected: asyncpg parses them on the way
in, which is why the asymmetry is easy to miss.
"""

from typing import Annotated, Any

from pydantic import BeforeValidator


def _stringify(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return value


def _stringify_scalar(value: Any) -> Any:
    """The scalar counterpart: a bare `inet` column, as on `agents.ip`."""
    if value is None or isinstance(value, str):
        return value
    return str(value)


StrList = Annotated[list[str], BeforeValidator(_stringify)]
NetAddr = Annotated[str, BeforeValidator(_stringify_scalar)]
