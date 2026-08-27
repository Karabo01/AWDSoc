"""Evidence snapshots - what makes 90-day retention survivable.

Member alerts vanish at 90 days. A resolved case from four months ago must still
show what it was about, so a trimmed snapshot is written onto the incident as
alerts attach: the first alert's normalised document, the most recent one, and
the entity set.

Capped, and never the full `raw`. An incident that accumulates forty alerts must
not accumulate forty raw Windows events in a jsonb column.
"""

import json
from datetime import datetime
from typing import Any

MAX_BYTES = 32 * 1024
MAX_ENTITIES_PER_TYPE = 50
# Enough to identify what happened without becoming a second copy of the alert.
MAX_ECS_FIELDS = 40


def _trim_ecs(ecs: dict) -> dict:
    if not isinstance(ecs, dict):
        return {}
    trimmed: dict[str, Any] = {}
    for key, value in list(ecs.items())[:MAX_ECS_FIELDS]:
        if isinstance(value, str) and len(value) > 512:
            value = value[:512] + "…"
        trimmed[key] = value
    return trimmed


def _merge_entities(existing: dict, related: dict[str, list[str]]) -> dict:
    merged = dict(existing) if isinstance(existing, dict) else {}
    for key, values in related.items():
        seen = merged.get(key) or []
        combined = list(dict.fromkeys([*seen, *values]))
        merged[key] = combined[:MAX_ENTITIES_PER_TYPE]
    return merged


def _fits(snapshot: dict) -> bool:
    return len(json.dumps(snapshot, default=str).encode()) <= MAX_BYTES


def update(
    evidence: dict | None,
    *,
    ecs: dict,
    related: dict[str, list[str]],
    timestamp: datetime,
    rule_desc: str,
    rule_level: int,
    is_first: bool,
) -> dict:
    """Fold one alert into the incident's snapshot."""
    snapshot = dict(evidence) if isinstance(evidence, dict) else {}

    if is_first or "first" not in snapshot:
        snapshot["first"] = {
            "at": timestamp.isoformat(),
            "rule_desc": rule_desc,
            "rule_level": rule_level,
            "ecs": _trim_ecs(ecs),
        }

    snapshot["latest"] = {
        "at": timestamp.isoformat(),
        "rule_desc": rule_desc,
        "rule_level": rule_level,
        "ecs": _trim_ecs(ecs),
    }
    snapshot["entities"] = _merge_entities(snapshot.get("entities", {}), related)

    if _fits(snapshot):
        return snapshot

    # Over budget. Shed the least valuable part first: the latest document's
    # detail, then the entity set. `first` is what an analyst reads in a closed
    # case, so it goes last.
    snapshot["latest"]["ecs"] = {}
    if _fits(snapshot):
        snapshot["truncated"] = True
        return snapshot

    snapshot["entities"] = {
        key: values[:5] for key, values in snapshot.get("entities", {}).items()
    }
    snapshot["truncated"] = True
    if _fits(snapshot):
        return snapshot

    snapshot["first"]["ecs"] = {}
    return snapshot
