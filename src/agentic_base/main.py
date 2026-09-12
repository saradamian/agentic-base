"""Application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_client import start_http_server
from prometheus_fastapi_instrumentator import Instrumentator

from agentic_base.config import get_settings
from agentic_base.db import get_engine, init_db
from agentic_base.observability.tracing import configure_tracing
from agentic_base.routers.health import health_api_prefix
from agentic_base.routers.health import router as health_router
from agentic_base.routers.runs import router as runs_router
from agentic_base.utils.logging import LogMiddleware, setup_logging


def get_app() -> FastAPI:
    """Create an Fastapi app instance."""
    settings = get_settings()

    setup_logging(json_logs=settings.log_json_format, log_level=settings.log_level)
    logger = structlog.get_logger(__name__)

    init_db()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """
        Handle startup and shutdown events.

        To understand more, read https://fastapi.tiangolo.com/advanced/events/.
        """
        await logger.adebug({"settings": settings.model_dump()})
        yield
        # Close pooled connections. Python 3.13+ reports a sqlite connection that is
        # garbage-collected open, and under warnings-as-errors that is a failure.
        get_engine().dispose()

    app = FastAPI(
        openapi_url="/openapi.json",
        docs_url="/docs",
        lifespan=lifespan,
        title=settings.project_name,
    )

    Instrumentator().instrument(app, metric_namespace="fastapi")
    configure_tracing(app, excluded_urls=f"{health_api_prefix}.*")

    if settings.metrics_port:
        start_http_server(settings.metrics_port)

    app.add_middleware(LogMiddleware, ignore_prefix=health_api_prefix)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=["*"])
    app.add_middleware(GZipMiddleware)

    app.include_router(health_router)
    app.include_router(runs_router)

    return app
