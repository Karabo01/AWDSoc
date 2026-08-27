import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

INCIDENT_STATUSES = ("new", "active", "pending", "resolved", "false_positive")
OPEN_STATUSES = ("new", "active", "pending")
CLOSED_STATUSES = ("resolved", "false_positive")
COMMENT_VISIBILITY = ("internal", "client")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "status in ('new','active','pending','resolved','false_positive')",
            name="incidents_status_check",
        ),
        UniqueConstraint("tenant_id", "number", name="incidents_tenant_number_uq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # Per-tenant sequential, user-facing.
    number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    # Max rule_level across members, on the 0-15 Wazuh ramp.
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    classification: Mapped[str | None] = mapped_column(Text)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rule_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Trimmed snapshot so a resolved case still reads after its alerts age out.
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    related_incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL")
    )

    # SLA. Deadlines are absolute and pushed forward on resume; `sla_paused_at`
    # is non-null exactly while the clock is stopped awaiting the client.
    sla_respond_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_resolve_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_paused_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IncidentComment(Base):
    __tablename__ = "incident_comments"
    __table_args__ = (
        CheckConstraint(
            "visibility in ('internal','client')", name="incident_comments_visibility_check"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default="internal")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
