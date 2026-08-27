from fastapi import APIRouter

from app.api.v1 import (
    admin,
    alerts,
    audit_log,
    auth,
    incidents,
    ingest,
    ingest_status,
    tenants,
)

api_router = APIRouter(prefix="/api/v1")
# Ingest is HMAC-authenticated, not JWT: it is included first and
# deliberately carries no bearer dependency.
api_router.include_router(ingest.router)
api_router.include_router(ingest_status.router)
api_router.include_router(auth.router)
api_router.include_router(incidents.router)
api_router.include_router(alerts.router)
api_router.include_router(audit_log.router)
api_router.include_router(tenants.router)
api_router.include_router(admin.router)
