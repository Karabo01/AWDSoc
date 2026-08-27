"""Entity upsert and linkage.

Every `related.*` value becomes an entity row scoped to its tenant, and every
entity touched by an incident is linked to it. The entity pages read these; the
alert pivot reads the GIN indexes on the arrays. Both are needed: the arrays
answer "which alerts touched this", the rows answer "what have we seen and said
about this".
"""

import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity, IncidentEntity

# One alert sweeping a /24 out of a firewall log should not create 254 entities.
MAX_PER_TYPE = 50

ARRAY_TO_TYPE = {
    "related_ip": "ip",
    "related_user": "user",
    "related_host": "host",
    "related_hash": "hash",
}


async def upsert_and_link(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    related: dict[str, list[str]],
    seen_at: datetime,
    primary_value: str = "",
) -> int:
    """Returns the number of entities touched. Does not commit."""
    touched = 0

    for array_name, entity_type in ARRAY_TO_TYPE.items():
        for value in (related.get(array_name) or [])[:MAX_PER_TYPE]:
            if not value:
                continue

            base = insert(Entity).values(
                tenant_id=tenant_id,
                type=entity_type,
                value=value,
                first_seen=seen_at,
                last_seen=seen_at,
                alert_count=1,
            )
            statement = base.on_conflict_do_update(
                index_elements=["tenant_id", "type", "value"],
                set_={
                    # first_seen only ever moves backwards, for a late arrival;
                    # last_seen only forwards, for an out-of-order one.
                    "first_seen": func.least(Entity.first_seen, base.excluded.first_seen),
                    "last_seen": func.greatest(Entity.last_seen, base.excluded.last_seen),
                    "alert_count": Entity.alert_count + 1,
                },
            ).returning(Entity.id)
            entity_id = await session.scalar(statement)
            if entity_id is None:
                continue

            role = "source" if value == primary_value else "observed"
            await session.execute(
                insert(IncidentEntity)
                .values(incident_id=incident_id, entity_id=entity_id, role=role)
                .on_conflict_do_nothing(index_elements=["incident_id", "entity_id"])
            )
            touched += 1

    return touched
