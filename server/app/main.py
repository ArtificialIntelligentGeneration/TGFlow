import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .core.config import get_settings
from pythonjsonlogger import jsonlogger
from .metrics import REQUEST_COUNT, REQUEST_LATENCY


def configure_logging() -> None:
    level = getattr(logging, get_settings().LOG_LEVEL.upper(), logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(level)
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.handlers = [handler]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SLAVA Licensing API", version="0.1.0")

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start = datetime.now()
        response = await call_next(request)
        elapsed = (datetime.now() - start).total_seconds()
        labels = (request.method, request.url.path, str(response.status_code))
        REQUEST_LATENCY.labels(*labels).observe(elapsed)
        REQUEST_COUNT.labels(*labels).inc()
        return response

    # Error handler for 422 to map to required format
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logging.exception("Unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    @app.get("/metrics")
    async def metrics():
        return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)

    # Routers
    from .api.routes.auth import router as auth_router
    from .api.routes.license import router as license_router
    from .api.routes.plans import router as plans_router
    from .api.routes.usage import router as usage_router
    from .api.routes.jwks import router as jwks_router

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(license_router, tags=["license"])
    app.include_router(plans_router, tags=["plans"])
    app.include_router(usage_router, prefix="/usage", tags=["usage"])
    app.include_router(jwks_router, tags=["jwks"])

    # Redis client for rate limiting & background jobs
    app.state.redis: Optional[aioredis.Redis] = None

    @app.on_event("startup")
    async def on_startup():
        configure_logging()
        settings = get_settings()
        logging.info("startup_config", extra={"event": "startup", "db_url": settings.DATABASE_URL, "redis_url": settings.REDIS_URL})
        try:
            app.state.redis = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
            # Simple ping to validate connection; if fails, continue without RL
            await app.state.redis.ping()
            logging.info("Connected to Redis for rate limiting")
        except Exception as e:  # noqa: BLE001
            app.state.redis = None
            logging.warning("Redis unavailable: %s", e)

        # Start cleanup task
        app.state.cleanup_task = asyncio.create_task(_cleanup_loop())

    @app.on_event("shutdown")
    async def on_shutdown():
        task: Optional[asyncio.Task] = getattr(app.state, "cleanup_task", None)
        if task:
            task.cancel()
        if app.state.redis is not None:
            await app.state.redis.close()

    return app


async def _cleanup_loop():
    from .services.usage_service import cleanup_expired_reservations
    while True:
        try:
            await cleanup_expired_reservations()
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logging.error("Cleanup error: %s", e)
        await asyncio.sleep(60)


app = create_app()


