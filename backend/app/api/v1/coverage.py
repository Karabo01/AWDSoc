"""MITRE ATT&CK coverage.

This reports what we have **detected**, not what a client's ruleset could in
principle detect. A rule that exists and has never fired tells an analyst nothing
about that client's exposure; a technique that fired forty times last week tells
them where to look. So every number here comes from `alerts`, inside the caller's
tenancy and inside an explicit window.

`mitre_ids` and `mitre_tactics` arrive from Wazuh as two independent arrays on the
same alert, not as pairs. There is no reliable technique-to-tactic mapping in the
payload, so the two breakdowns are computed independently and a tactic's
`technique_count` is "distinct techniques seen on alerts that also carried this
tactic". That is an approximation, and it is named as one rather than dressed up
as a join.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps.auth import CurrentUser, accessible_tenant_ids
from app.deps.tenancy import TenantScope, get_tenant_scope
from app.schemas.agent import CoverageReport, TacticCoverage, TechniqueCoverage

router = APIRouter(prefix="/coverage", tags=["coverage"])

Session = Annotated[AsyncSession, Depends(get_session)]
Scope = Annotated[TenantScope, Depends(get_tenant_scope)]

MAX_TECHNIQUES = 200


async def _tenant_filter(session: AsyncSession, user, scope: TenantScope) -> list[uuid.UUID] | None:
    """The tenancy this report covers. None means every tenant, which only a
    platform-wide staff token without an access list can reach."""
    if scope.tenant_id is not None:
        return [scope.tenant_id]
    return await accessible_tenant_ids(session, user)


def _sql(body: str, tenants: list[uuid.UUID] | None) -> str:
    scope_clause = "" if tenants is None else " and tenant_id = any(:tenants)"
    return body.format(scope=scope_clause)


TECHNIQUES_SQL = """
    select t.technique                       as technique_id,
           count(*)                          as alert_count,
           count(distinct a.incident_id)     as incident_count,
           max(a.timestamp)                  as last_seen,
           max(a.rule_level)                 as max_severity
      from alerts a
      cross join lateral unnest(a.mitre_ids) as t(technique)
     where a.timestamp >= :since{scope}
     group by t.technique
     order by alert_count desc
     limit :limit
"""

TACTICS_SQL = """
    select t.tactic                            as tactic,
           -- The technique join multiplies rows, so the alert count must be
           -- distinct on the alert or it reports techniques, not alerts.
           count(distinct a.id)                as alert_count,
           count(distinct technique.technique) as technique_count
      from alerts a
      cross join lateral unnest(a.mitre_tactics) as t(tactic)
      left join lateral unnest(a.mitre_ids) as technique(technique) on true
     where a.timestamp >= :since{scope}
     group by t.tactic
     order by alert_count desc
"""

TOTALS_SQL = """
    select count(*)                                              as total,
           count(*) filter (where cardinality(mitre_ids) = 0)    as unmapped
      from alerts a
     where a.timestamp >= :since{scope}
"""


@router.get("/mitre", response_model=CoverageReport)
async def mitre_coverage(
    user: CurrentUser,
    session: Session,
    scope: Scope,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> CoverageReport:
    """Bounded to 90 days at most. `alerts` is partitioned by timestamp, so the
    window is what keeps this from touching every partition ever created."""
    tenants = await _tenant_filter(session, user, scope)
    since = datetime.now(UTC) - timedelta(days=days)

    if tenants is not None and not tenants:
        # A staff user with an empty access list sees nothing, not everything.
        return CoverageReport(since=since)

    params: dict = {"since": since}
    binds = []
    if tenants is not None:
        params["tenants"] = tenants
        binds.append(bindparam("tenants", type_=ARRAY(UUID(as_uuid=True))))

    def statement(body: str):
        stmt = text(_sql(body, tenants))
        return stmt.bindparams(*binds) if binds else stmt

    technique_rows = (
        await session.execute(statement(TECHNIQUES_SQL), {**params, "limit": MAX_TECHNIQUES})
    ).all()
    tactic_rows = (await session.execute(statement(TACTICS_SQL), params)).all()
    totals = (await session.execute(statement(TOTALS_SQL), params)).one()

    return CoverageReport(
        since=since,
        techniques=[
            TechniqueCoverage(
                technique_id=row.technique_id,
                alert_count=row.alert_count,
                incident_count=row.incident_count,
                last_seen=row.last_seen,
                max_severity=row.max_severity or 0,
            )
            for row in technique_rows
        ],
        tactics=[
            TacticCoverage(
                tactic=row.tactic,
                alert_count=row.alert_count,
                technique_count=row.technique_count,
            )
            for row in tactic_rows
        ],
        total_alerts=totals.total,
        unmapped_alerts=totals.unmapped,
    )
