"""Incident fingerprinting.

Deliberately coarse. Coarse grouping produces fewer, fatter incidents, which is
the right failure mode for an MSSP: an analyst covering six clients would rather
open one incident with forty alerts than forty incidents.

`tenant_id` is inside the hash, so two clients can never share an incident even
if every other component matches.

M3 computes this with an empty `primary_entity`, because resolving one requires
the normalised document that M4 produces. Reprocessing recomputes it, which is
safe while no incidents exist yet - and is the reason M5 must not start before
M4's replay has run.
"""

import hashlib
import uuid


def fingerprint(
    *,
    tenant_id: uuid.UUID | str,
    rule_id: int,
    agent_id: str | None,
    primary_entity: str = "",
) -> str:
    material = f"{tenant_id}|{rule_id}|{agent_id or ''}|{primary_entity}"
    return hashlib.sha256(material.encode()).hexdigest()


def primary_entity(ecs: dict) -> str:
    """First match wins: source.ip -> user.name -> host.name -> "".

    Reads the normalised document, never the raw alert - that is what keeps the
    fingerprint stable across Wazuh versions and decoder changes.
    """
    for path in ("source.ip", "user.name", "host.name"):
        value = ecs.get(path)
        if isinstance(value, dict | list):
            continue
        if value not in (None, ""):
            return str(value)
    return ""
