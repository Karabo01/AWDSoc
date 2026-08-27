"""Tenant onboarding schemas.

Two fields must never appear in a response model in this file, and there is a test
that walks the OpenAPI schema to prove it: `ingest_secret` (except in the
write-once payloads below, which are named to make that obvious) and anything
derived from `password_enc`.
"""

import ipaddress
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.types import StrList

# The slug lands in a public ingest URL, so it is URL-safe by construction rather
# than by escaping at the point of use.
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


def _validate_cidrs(values: list[str]) -> list[str]:
    normalised = []
    for value in values:
        try:
            normalised.append(str(ipaddress.ip_network(value, strict=False)))
        except ValueError as exc:
            raise ValueError(f"{value!r} is not a valid CIDR") from exc
    return normalised


class WazuhConnectionIn(BaseModel):
    base_url: str = Field(max_length=500)
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)
    verify_ssl: bool = True
    # Set only on a shared manager: the agent group that scopes this tenant.
    agent_group: str | None = Field(default=None, max_length=200)

    @field_validator("base_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("base_url must be https - this crosses the public internet")
        return value


class WazuhConnectionUpdate(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    username: str | None = Field(default=None, max_length=200)
    # Omitted means "leave the stored credential alone".
    password: str | None = Field(default=None, min_length=1, max_length=500)
    verify_ssl: bool | None = None
    agent_group: str | None = Field(default=None, max_length=200)

    @field_validator("base_url")
    @classmethod
    def _https_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("base_url must be https - this crosses the public internet")
        return value


class WazuhConnectionRead(BaseModel):
    """Deliberately has no password field of any kind."""

    model_config = ConfigDict(from_attributes=True)

    base_url: str
    username: str
    verify_ssl: bool
    agent_group: str | None
    last_sync_at: datetime | None
    last_sync_error: str | None


class SlaBand(BaseModel):
    severity_min: int = Field(ge=0, le=15)
    respond_minutes: int = Field(gt=0)
    resolve_minutes: int = Field(gt=0)

    @model_validator(mode="after")
    def _resolve_is_not_tighter_than_respond(self) -> "SlaBand":
        if self.resolve_minutes < self.respond_minutes:
            raise ValueError("resolve_minutes cannot be shorter than respond_minutes")
        return self


class SlaPolicy(BaseModel):
    """The whole policy for a tenant. PUT replaces it; there is no partial edit.

    An empty band list means this tenant has no SLA and shows no countdown.
    """

    bands: list[SlaBand] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def _bands_are_distinct_and_ordered(self) -> "SlaPolicy":
        floors = [band.severity_min for band in self.bands]
        if len(set(floors)) != len(floors):
            raise ValueError("each severity_min may appear only once")
        self.bands.sort(key=lambda band: band.severity_min)
        # A tighter band above a looser one is almost always a typo: severity 13
        # should not be given more time than severity 7.
        for lower, higher in zip(self.bands, self.bands[1:], strict=False):
            if higher.respond_minutes > lower.respond_minutes:
                raise ValueError(
                    f"severity {higher.severity_min} is given more response time than "
                    f"severity {lower.severity_min}; higher severity must be tighter"
                )
        return self


class TenantCreate(BaseModel):
    slug: str
    name: str = Field(min_length=1, max_length=200)
    alert_floor: int = Field(default=7, ge=0, le=15)
    grouping_window_minutes: int = Field(default=30, gt=0, le=1440)
    ingest_cidrs: list[str] = Field(default_factory=list, max_length=32)
    colour: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    connection: WazuhConnectionIn | None = None
    sla: SlaPolicy | None = None

    @field_validator("slug")
    @classmethod
    def _slug_is_url_safe(cls, value: str) -> str:
        value = value.strip().lower()
        if not SLUG_PATTERN.match(value):
            raise ValueError(
                "slug must be 3-40 characters of lowercase letters, digits and hyphens, "
                "starting and ending with a letter or digit"
            )
        return value

    @field_validator("ingest_cidrs")
    @classmethod
    def _cidrs_are_valid(cls, values: list[str]) -> list[str]:
        return _validate_cidrs(values)


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = None
    alert_floor: int | None = Field(default=None, ge=0, le=15)
    grouping_window_minutes: int | None = Field(default=None, gt=0, le=1440)
    ingest_cidrs: list[str] | None = Field(default=None, max_length=32)
    colour: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    connection: WazuhConnectionUpdate | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str | None) -> str | None:
        if value is not None and value not in ("active", "suspended", "offboarding"):
            raise ValueError("status must be active, suspended or offboarding")
        return value

    @field_validator("ingest_cidrs")
    @classmethod
    def _cidrs_are_valid(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else _validate_cidrs(values)


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    status: str
    alert_floor: int
    grouping_window_minutes: int
    # cidr[] arrives from asyncpg as IPv4Network objects, not strings.
    ingest_cidrs: StrList = Field(default_factory=list)
    colour: str | None
    created_at: datetime
    connection: WazuhConnectionRead | None = None
    sla: SlaPolicy | None = None


class TenantSecretRevealed(BaseModel):
    """The one and only time an ingest secret is returned.

    Named to make a reviewer look twice. It is not stored anywhere client-side by
    the console and cannot be read back - rotation is the only recovery.
    """

    tenant: TenantRead
    ingest_secret: str
    ingest_url: str
    # Paste-ready for the client's ossec.conf.
    integration_block: str
    install_command: str


class ConnectionCheckResult(BaseModel):
    ok: bool
    error: str | None = None
    manager_version: str | None = None
    node_name: str | None = None
    agent_count: int | None = None
    agent_group: str | None = None
    agent_group_exists: bool | None = None
    agent_group_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
