"""Indexes M7 reads.

`agents` was created in 0001 with only its `(tenant_id, agent_id)` primary key,
which is the sync's upsert path and nothing else. M7 adds three more access
patterns, plus one on `alerts`:

* the fleet list, ordered by name within a tenant;
* the group filter, which is a containment test on an array;
* the agent detail page, which looks up by `agent_id` across tenants precisely so
  it can report the same id appearing under two of them;
* `alerts` filtered by agent and ordered by time - the agent's own alert list and
  the 24-hour counts on the overview. Without it those fall back to
  `alerts_tenant_ts_idx` and filter `agent_id` after the fact.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create index agents_tenant_name_idx on agents (tenant_id, name)")
    op.execute("create index agents_groups_idx on agents using gin (groups)")
    op.execute("create index agents_agent_id_idx on agents (agent_id)")

    # Created on the partitioned parent, so Postgres builds it on every existing
    # partition and on every future one the worker rolls forward.
    op.execute(
        "create index alerts_tenant_agent_ts_idx "
        "on alerts (tenant_id, agent_id, timestamp desc)"
    )


def downgrade() -> None:
    op.execute("drop index if exists alerts_tenant_agent_ts_idx")
    op.execute("drop index if exists agents_agent_id_idx")
    op.execute("drop index if exists agents_groups_idx")
    op.execute("drop index if exists agents_tenant_name_idx")
