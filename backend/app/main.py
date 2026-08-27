import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.api.v1 import health as health_routes
from app.config import settings
from app.redis_client import close_redis

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger(settings.app_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting %s (%s)", settings.app_name, settings.environment)
    yield
    await close_redis()


app = FastAPI(
    title="AWDTECH SOC Console",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.environment != "production" else None,
)

# Served same-origin behind Traefik: /api here, everything else to web. No CORS.
app.include_router(health_routes.router)
app.include_router(api_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Something broke on our side. The error has been logged."},
    )
