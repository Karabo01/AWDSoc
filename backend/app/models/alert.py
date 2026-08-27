import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Alert(Base):
    """Raw + normalised alert, partitioned monthly by `timestamp`.

    Two consequences of partitioning that cannot be worked around: every unique
    constraint must include the partition key, and the primary key is composite.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "wazuh_id", "timestamp", name="alerts_tenant_wazuh_uq"),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    wazuh_id: Mapped[str] = mapped_column(Text, nullable=False)
    # Alert time, not receipt time. This is the partition key.
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    rule_id: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rule_desc: Mapped[str] = mapped_column(Text, nullable=False)
    rule_groups: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    mitre_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    mitre_tactics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    agent_id: Mapped[str | None] = mapped_column(Text)
    agent_name: Mapped[str | None] = mapped_column(Text)

    ecs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    map_version: Mapped[int] = mapped_column(Integer, nullable=False)

    related_ip: Mapped[list[str]] = mapped_column(ARRAY(INET), nullable=False, server_default="{}")
    related_user: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    related_host: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    related_hash: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    # No FK: incidents outlive alerts, and a real FK would either block partition
    # drops or cascade damage into closed cases.
    incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
