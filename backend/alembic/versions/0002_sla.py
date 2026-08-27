"""Per-tenant SLA policy, and the incident clock that pauses awaiting the client.

Deadlines are absolute timestamps pushed forward on resume rather than an elapsed
accumulator, so the queue still orders by one indexed column. `sla_paused_seconds`
is kept alongside because escalation recomputes against it - without it, a
re-tightened deadline would claw back time the client already held.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table tenant_slas (
          tenant_id       uuid not null references tenants(id) on delete cascade,
          severity_min    smallint not null check (severity_min between 0 and 15),
          respond_minutes integer not null check (respond_minutes > 0),
          resolve_minutes integer not null check (resolve_minutes > 0),
          check (resolve_minutes >= respond_minutes),
          primary key (tenant_id, severity_min)
        )
    """)

    op.execute("""
        alter table incidents
          add column sla_respond_by     timestamptz,
          add column sla_resolve_by     timestamptz,
          add column sla_paused_at      timestamptz,
          add column sla_paused_seconds integer not null default 0,
          add column first_response_at  timestamptz
    """)

    # Breach-imminent ordering, cross-tenant. A paused clock is not ticking and
    # must not appear here.
    op.execute("""
        create index incidents_sla_respond_idx on incidents (sla_respond_by)
          where first_response_at is null and sla_paused_at is null
            and status in ('new','active','pending')
    """)
    op.execute("""
        create index incidents_sla_resolve_idx on incidents (sla_resolve_by)
          where sla_paused_at is null and status in ('new','active','pending')
    """)


def downgrade() -> None:
    op.execute("drop index if exists incidents_sla_resolve_idx")
    op.execute("drop index if exists incidents_sla_respond_idx")
    op.execute("""
        alter table incidents
          drop column if exists first_response_at,
          drop column if exists sla_paused_seconds,
          drop column if exists sla_paused_at,
          drop column if exists sla_resolve_by,
          drop column if exists sla_respond_by
    """)
    op.execute("drop table if exists tenant_slas")
