"""Indexes the entity index actually reads.

Three gaps M6 exposes:

1. The list orders by `last_seen desc` across all types. The existing
   `entities_tenant_type_idx` leads with `type`, so an unfiltered list could not
   use it for ordering.

2. Search is `value ILIKE '%q%'`. A leading wildcard defeats a btree entirely, so
   this is a GIN trigram index. `pg_trgm` ships with the standard Postgres image
   and with the Alpine one used in the deployment.

3. `incident_entities` had only its `(incident_id, entity_id)` primary key, which
   answers "entities on this incident" but not "incidents for this entity" -
   exactly the direction the entity page reads. Without the reverse index that
   pivot is a sequential scan of the whole link table.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('create extension if not exists "pg_trgm"')

    op.execute(
        "create index entities_tenant_last_seen_idx on entities (tenant_id, last_seen desc)"
    )
    op.execute(
        "create index entities_value_trgm_idx on entities using gin (value gin_trgm_ops)"
    )
    op.execute(
        "create index incident_entities_entity_idx on incident_entities (entity_id)"
    )


def downgrade() -> None:
    op.execute("drop index if exists incident_entities_entity_idx")
    op.execute("drop index if exists entities_value_trgm_idx")
    op.execute("drop index if exists entities_tenant_last_seen_idx")
    # pg_trgm is left installed: dropping an extension another object may come to
    # depend on is not something a downgrade should decide.
