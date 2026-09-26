"""FastAPI application factory with lifecycle-owned dependency injection."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from logagent.errors import LogAgentError
from logagent.lifecycle import ApplicationLifecycle
from logagent.models import SystemConfig

from .agent_routers import agent_router
from .channel_routers import router as channel_router
from .dependencies import Lifecycle
from .errors import (
    logagent_error_handler,
    pydantic_error_handler,
    request_validation_handler,
    unhandled_error_handler,
)
from .routers import router
from .test_channel_routers import router as test_channel_router


def create_app(lifecycle: Lifecycle | None = None) -> FastAPI:
    owner = lifecycle or ApplicationLifecycle(SystemConfig())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.lifecycle = owner
        app.state.services = await owner.start()
        try:
            yield
        finally:
            await owner.shutdown()
            app.state.services = None

    application = FastAPI(
        title="LogAgent API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_exception_handler(LogAgentError, logagent_error_handler)
    application.add_exception_handler(RequestValidationError, request_validation_handler)
    application.add_exception_handler(ValidationError, pydantic_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)
    application.include_router(agent_router, prefix="/api")
    application.include_router(channel_router, prefix="/api")
    application.include_router(test_channel_router, prefix="/api")
    application.include_router(router, prefix="/api")
    return application


app = create_app()
