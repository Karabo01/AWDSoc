import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# AWDTECH staff have tenant_id NULL and is_staff true.
# Client users have a fixed tenant_id and is_staff false.
ROLES = ("platform_admin", "soc_analyst", "client_admin", "client_viewer")
STAFF_ROLES = ("platform_admin", "soc_analyst")
CLIENT_ROLES = ("client_admin", "client_viewer")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role in ('platform_admin','soc_analyst','client_admin','client_viewer')",
            name="users_role_check",
        ),
        CheckConstraint(
            "(is_staff and tenant_id is null) or (not is_staff and tenant_id is not null)",
            name="users_tenancy_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    is_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StaffTenantAccess(Base):
    """Optional narrowing of which tenants a staff member may see.

    No rows for a staff user means every tenant.
    """

    __tablename__ = "staff_tenant_access"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
