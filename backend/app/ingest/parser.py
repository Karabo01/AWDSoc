"""Wazuh alert -> alerts row.

M3 stores the alert verbatim in `raw` and leaves `ecs` empty; M4's normalisation
engine fills it in and can replay from `raw` at any time. Two sentinel values on
`map_version` distinguish the cases that look alike in a query:

    0   not normalised yet (this milestone)
   -1   normalisation was attempted and threw (DESIGN.md §5)

Nothing here may raise on bad input. A malformed decoder on one client must not
stop the pipeline for every client, so every field degrades to a default and the
row still lands - `raw` is preserved either way, so a bad parse is recoverable.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

NOT_NORMALISED = 0
NORMALISATION_FAILED = -1

MAX_RULE_LEVEL = 15


@dataclass
class ParsedAlert:
    wazuh_id: str
    timestamp: datetime
    rule_id: int
    rule_level: int
    rule_desc: str
    rule_groups: list[str] = field(default_factory=list)
    mitre_ids: list[str] = field(default_factory=list)
    mitre_tactics: list[str] = field(default_factory=list)
    agent_id: str | None = None
    agent_name: str | None = None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return [str(value)]


def parse_timestamp(value: Any) -> datetime | None:
    """Wazuh emits e.g. 2026-08-27T09:15:00.123+0000."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # Older Wazuh builds omit the colon in the offset; fromisoformat handles
        # that from 3.11, but a Z suffix still needs help on some inputs.
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict:
    """A decoder can put anything here. Anything that is not an object is
    treated as absent rather than allowed to crash the consumer."""
    return value if isinstance(value, dict) else {}


def parse(alert: dict, *, received_at: datetime | None = None) -> ParsedAlert:
    received_at = received_at or datetime.now(UTC)
    rule = _as_dict(alert.get("rule"))
    agent = _as_dict(alert.get("agent"))
    mitre = _as_dict(rule.get("mitre"))

    timestamp = parse_timestamp(alert.get("timestamp"))
    if timestamp is None:
        # Receipt time is wrong but bounded; dropping the alert would be worse.
        log.warning("alert %s has an unparseable timestamp", alert.get("id"))
        timestamp = received_at

    level = _as_int(rule.get("level"))
    if not 0 <= level <= MAX_RULE_LEVEL:
        log.warning("alert %s has rule level %s outside 0-15", alert.get("id"), level)
        level = max(0, min(level, MAX_RULE_LEVEL))

    # `id` is the Wazuh alert id and the natural dedup key alongside timestamp.
    # A missing one is unusual but must not lose the alert.
    wazuh_id = str(alert.get("id") or "").strip()
    if not wazuh_id:
        wazuh_id = f"noid-{timestamp.timestamp():.6f}"

    return ParsedAlert(
        wazuh_id=wazuh_id,
        timestamp=timestamp,
        rule_id=_as_int(rule.get("id")),
        rule_level=level,
        rule_desc=str(rule.get("description") or "")[:2000] or "(no description)",
        rule_groups=_as_list(rule.get("groups")),
        mitre_ids=_as_list(mitre.get("id")),
        mitre_tactics=_as_list(mitre.get("tactic")),
        agent_id=str(agent["id"]) if agent.get("id") is not None else None,
        agent_name=str(agent["name"]) if agent.get("name") is not None else None,
    )
