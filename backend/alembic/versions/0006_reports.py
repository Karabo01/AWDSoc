"""Client reports, stored as snapshots.

`alerts` is partitioned and dropped past `ALERT_RETENTION_DAYS`, so the figures
behind a report stop existing months after it was sent. Regenerating a March
report in September would quietly produce different numbers than the ones the
client has in their inbox, which is the worst possible way to lose a contractual
argument. The payload is therefore computed once and stored as `jsonb`.

`status` is `draft` or `issued`, and issuing is one way — enforced in the
handlers rather than by a constraint, because "issued" is about intent and the
database cannot tell a correction from a rewrite.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        create table reports (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null references tenants(id) on delete cascade,
          number        bigint not null,
          title         text not null,
          status        text not null default 'draft'
                          check (status in ('draft','issued')),
          period_start  timestamptz not null,
          period_end    timestamptz not null,
          summary_note  text,
          payload       jsonb not null default '{}',
          generated_by  uuid references users(id) on delete set null,
          generated_at  timestamptz not null default now(),
          issued_at     timestamptz,
          constraint reports_tenant_number_uq unique (tenant_id, number),
          constraint reports_period_check check (period_end > period_start)
        )
    """)

    # The list, per tenant, newest period first.
    op.execute(
        "create index reports_tenant_period_idx on reports (tenant_id, period_end desc)"
    )
    # A client user only ever reads issued reports, so that filter leads.
    op.execute("""
        create index reports_issued_idx on reports (tenant_id, issued_at desc)
          where status = 'issued'
    """)


def downgrade() -> None:
    op.execute("drop index if exists reports_issued_idx")
    op.execute("drop index if exists reports_tenant_period_idx")
    op.execute("drop table if exists reports")
