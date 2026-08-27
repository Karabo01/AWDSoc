"""`related.*` extraction - the thing that makes entity pivoting possible.

One query on `related_ip @> ARRAY['41.1.2.3'::inet]` returns every alert touching
that address whether it was source, destination, or buried in a log line. Without
these arrays you have an alert list; with them you have a pivotable graph.

Values are collected regardless of role. An address that was the source in one
alert and the destination in another is the same entity, and an analyst pivoting
on it wants both.
"""

import ipaddress
import logging
import re
from typing import Any

from app.normalisation.engine import Mapping

log = logging.getLogger(__name__)

# Deliberately loose; every candidate is validated by `ipaddress` afterwards.
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_RE = re.compile(r"\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b")
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")

HASH_LENGTHS = {32, 40, 64, 128}  # md5, sha1, sha256, sha512

# Wazuh decoders use several spellings of "this field was empty".
_PLACEHOLDERS = {"", "-", "--", "n/a", "na", "null", "(null)", "none", "nil", "unknown"}

# An entity page for a loopback address is noise in every tenant. Private ranges
# are kept: 10.x is exactly what an analyst pivots on during lateral movement.
def _is_useful_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (address.is_loopback or address.is_unspecified or address.is_reserved)


def _scalars(value: Any) -> list[str]:
    """Flatten a field value to the strings worth inspecting."""
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, str | int | float):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_scalars(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_scalars(item))
        return out
    return []


def _clean(text: str) -> str:
    return text.strip().rstrip(".")


def _is_placeholder(text: str) -> bool:
    return _clean(text).lower() in _PLACEHOLDERS


def as_ip(text: str) -> str | None:
    """Normalised string form, or None if this is not a usable address."""
    candidate = _clean(text)
    # A bare port suffix is common in Windows event data.
    if candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.split(":")[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return str(address) if _is_useful_ip(address) else None


def as_hash(text: str) -> str | None:
    candidate = _clean(text)
    if len(candidate) in HASH_LENGTHS and _HEX_RE.match(candidate):
        return candidate.lower()
    return None


class _Collector:
    """Order-preserving, with case-insensitive de-duplication.

    Usernames are matched case-insensitively but stored as observed, because
    `Administrator` and `administrator` are one account and an analyst should see
    which spelling the log actually used.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.values: list[str] = []

    def add(self, value: str | None) -> None:
        if not value:
            return
        value = _clean(value)
        if not value or _is_placeholder(value):
            return
        key = value.lower()
        if key in self._seen:
            return
        self._seen.add(key)
        self.values.append(value)


def extract(
    ecs: dict, raw: dict, mapping: Mapping, *, rule_groups: list[str] | None = None
) -> dict[str, list[str]]:
    """Returns the four `related_*` arrays for one alert."""
    ips, users, hosts, hashes = _Collector(), _Collector(), _Collector(), _Collector()

    for field_name, value in ecs.items():
        strings = _scalars(value)

        if field_name in mapping.user_fields:
            for text in strings:
                users.add(text)
            continue

        if field_name in mapping.host_fields:
            for text in strings:
                hosts.add(text)
            # A hostname field can hold an address; keep both readings.
            for text in strings:
                ips.add(as_ip(text))
            continue

        is_hash_field = ".hash" in field_name
        for text in strings:
            if is_hash_field:
                # Trust the field name over the shape: a truncated or oddly
                # formatted hash is still the hash we were given.
                hashes.add(as_hash(text) or _clean(text).lower())
                continue
            ips.add(as_ip(text))
            hashes.add(as_hash(text))

    # A regex sweep over every alert's full_log would be expensive and noisy, so
    # the map carries an allowlist of groups known to embed addresses.
    groups = set(rule_groups or [])
    if groups & mapping.full_log_ip_scan_groups:
        full_log = raw.get("full_log")
        if isinstance(full_log, str):
            for match in _IPV4_RE.findall(full_log):
                ips.add(as_ip(match))
            for match in _IPV6_RE.findall(full_log):
                ips.add(as_ip(match))

    # The agent is always a host, whether or not the map produced host.name.
    agent = raw.get("agent")
    if isinstance(agent, dict):
        if agent.get("name"):
            hosts.add(str(agent["name"]))
        if agent.get("ip"):
            ips.add(as_ip(str(agent["ip"])))

    return {
        "related_ip": ips.values,
        "related_user": users.values,
        "related_host": hosts.values,
        "related_hash": hashes.values,
    }
