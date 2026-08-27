"""Per-tenant incident numbering.

`incidents.number` is user-facing and sequential per tenant, which rules out a
shared sequence. Deriving it from `max(number) + 1` races under concurrent
arrival - two alerts landing together would both read the same maximum and one
would lose to the unique constraint.

A counter row with `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` is atomic:
the row lock serialises exactly the writers that need serialising, per tenant,
without touching any other tenant's throughput.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table tenant_counters (
          tenant_id            uuid primary key references tenants(id) on delete cascade,
          next_incident_number bigint not null default 1
        )
    """)

    # Existing tenants start after whatever numbers already exist.
    op.execute("""
        insert into tenant_counters (tenant_id, next_incident_number)
        select t.id, coalesce(max(i.number), 0) + 1
        from tenants t
        left join incidents i on i.tenant_id = t.id
        group by t.id
    """)

    # The queue's default ordering, per tenant and cross-tenant.
    op.execute("""
        create index incidents_tenant_open_idx on incidents (tenant_id, last_seen desc)
          where status in ('new','active','pending')
    """)


def downgrade() -> None:
    op.execute("drop index if exists incidents_tenant_open_idx")
    op.execute("drop table if exists tenant_counters")
