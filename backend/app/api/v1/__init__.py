from fastapi import APIRouter

from app.api.v1 import (
    admin,
    agents,
    alerts,
    audit_log,
    auth,
    coverage,
    entities,
    incidents,
    ingest,
    ingest_status,
    overview,
    rules,
    stream,
    tenants,
    users,
)

# Carries no prefix of its own: main.py mounts it at both /api/v1 and /v1
# so the app works whether or not the proxy strips the /api prefix.
api_router = APIRouter()
# Ingest is HMAC-authenticated, not JWT: it is included first and
# deliberately carries no bearer dependency.
api_router.include_router(ingest.router)
api_router.include_router(ingest_status.router)
api_router.include_router(auth.router)
# Before the incidents router: `/incidents/stream` must match as a literal,
# not as an incident id, and route order is what decides that.
api_router.include_router(stream.router)
api_router.include_router(incidents.router)
api_router.include_router(alerts.router)
api_router.include_router(entities.router)
api_router.include_router(agents.router)
api_router.include_router(rules.router)
api_router.include_router(coverage.router)
api_router.include_router(overview.router)
api_router.include_router(users.router)
api_router.include_router(audit_log.router)
api_router.include_router(tenants.router)
api_router.include_router(admin.router)
