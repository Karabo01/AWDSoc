"""Report schemas.

`payload` is deliberately a bare `dict` rather than a nested model. It is a
*snapshot*: a report issued today must still render in two years, after the
builder has grown fields and dropped others. Validating an old payload against
today's model would fail on exactly the reports that matter most — the old ones.
The `schema` key inside it carries the version instead.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["draft", "issued"]


class ReportCreate(BaseModel):
    """Generate a report for a period.

    The tenant comes from the token, never from here — see `api/v1/reports.py`.
    """

    period_start: datetime
    period_end: datetime
    title: str | None = Field(default=None, max_length=200)
    summary_note: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def _period_is_sane(self) -> "ReportCreate":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        if (self.period_end - self.period_start).days > 400:
            raise ValueError("a reporting period longer than 400 days is not supported")
        return self


class ReportUpdate(BaseModel):
    """Drafts only. An issued report is what the client received."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary_note: str | None = Field(default=None, max_length=8000)


class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str | None = None
    tenant_slug: str | None = None
    number: int
    title: str
    status: Status
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    generated_by_name: str | None = None
    issued_at: datetime | None = None


class ReportRead(ReportSummary):
    summary_note: str | None = None
    payload: dict = Field(default_factory=dict)


class ReportPreview(BaseModel):
    """An unsaved snapshot, for the analyst to look at before committing to it."""

    period_start: datetime
    period_end: datetime
    payload: dict = Field(default_factory=dict)
