import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

TENANT_STATUSES = ("active", "suspended", "offboarding")


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "status in ('active','suspended','offboarding')", name="tenants_status_check"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    ingest_secret: Mapped[str] = mapped_column(Text, nullable=False)
    ingest_cidrs: Mapped[list[str]] = mapped_column(
        ARRAY(CIDR), nullable=False, server_default="{}"
    )
    alert_floor: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="7")
    grouping_window_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="30"
    )
    # Quiet second channel for tenant identity in the queue (3px left border).
    colour: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    connection: Mapped["WazuhConnection | None"] = relationship(
        back_populates="tenant", uselist=False, cascade="all, delete-orphan"
    )


class WazuhConnection(Base):
    __tablename__ = "wazuh_connections"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    verify_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    agent_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)

    tenant: Mapped[Tenant] = relationship(back_populates="connection")


class TenantSla(Base):
    """Contractual response times, per tenant, by severity band.

    The row with the highest `severity_min` not exceeding the incident's severity
    wins. A tenant with no rows has no SLA and shows no countdown.
    """

    __tablename__ = "tenant_slas"
    __table_args__ = (
        CheckConstraint("severity_min between 0 and 15", name="tenant_slas_severity_check"),
        CheckConstraint("respond_minutes > 0", name="tenant_slas_respond_check"),
        CheckConstraint("resolve_minutes > 0", name="tenant_slas_resolve_check"),
        CheckConstraint(
            "resolve_minutes >= respond_minutes", name="tenant_slas_order_check"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    severity_min: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    respond_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolve_minutes: Mapped[int] = mapped_column(Integer, nullable=False)


class TenantCounter(Base):
    """Atomic per-tenant incident numbering.

    `max(number) + 1` races under concurrent arrival. This row lock serialises
    only the writers for one tenant.
    """

    __tablename__ = "tenant_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    next_incident_number: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="1"
    )
