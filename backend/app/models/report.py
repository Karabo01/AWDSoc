import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

REPORT_STATUSES = ("draft", "issued")


class Report(Base):
    """A client-facing security report, frozen at generation.

    **The payload is a snapshot, not a query.** `alerts` is partitioned and drops
    past `ALERT_RETENTION_DAYS`, so regenerating a March report in September would
    produce different numbers than the one the client was sent. A report that
    cannot be reproduced is worse than useless in a contractual conversation, so
    the figures are computed once and stored.

    `issued` is a one-way door. A draft can be regenerated and edited; an issued
    report is what the client received and is never rewritten.
    """

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint("status in ('draft','issued')", name="reports_status_check"),
        CheckConstraint("period_end > period_start", name="reports_period_check"),
        UniqueConstraint("tenant_id", "number", name="reports_tenant_number_uq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # Per-tenant sequential, user-facing, same contract as an incident number.
    number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # The analyst's covering note. The only prose in the report that a person
    # wrote rather than a query produced.
    summary_note: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
