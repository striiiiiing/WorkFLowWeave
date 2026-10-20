"""FastAPI application factory with lifecycle-owned dependency injection."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from workflowweave import __version__
from workflowweave.channel.login import ChannelLoginManager
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.lifecycle import ApplicationLifecycle
from workflowweave.models import SystemConfig
from workflowweave.plugins.channel.wechat_openclaw.node import warn_if_node_unavailable

from .agent_routers import agent_router
from .channel_routers import router as channel_router
from .dependencies import Lifecycle
from .errors import (
    pydantic_error_handler,
    request_validation_handler,
    unhandled_error_handler,
    workflowweave_error_handler,
)
from .login_routers import router as login_router
from .routers import router
from .static import WebAppFiles
from .test_channel_routers import router as test_channel_router


def create_app(
    lifecycle: Lifecycle | None = None, *, frontend_dir: Path | None = None,
) -> FastAPI:
    owner = lifecycle or ApplicationLifecycle(SystemConfig())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        warn_if_node_unavailable()
        app.state.lifecycle = owner
        app.state.services = await owner.start()
        app.state.channel_logins = ChannelLoginManager()
        try:
            yield
        finally:
            try:
                await app.state.channel_logins.close()
            finally:
                await owner.shutdown()
                app.state.services = None

    application = FastAPI(
        title="WorkFLowWeave API",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_exception_handler(WorkFLowWeaveError, workflowweave_error_handler)
    application.add_exception_handler(RequestValidationError, request_validation_handler)
    application.add_exception_handler(ValidationError, pydantic_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)
    application.include_router(agent_router, prefix="/api")
    application.include_router(channel_router, prefix="/api")
    application.include_router(test_channel_router, prefix="/api")
    application.include_router(login_router, prefix="/api")
    application.include_router(router, prefix="/api")
    web_root = frontend_dir or Path(str(files("workflowweave").joinpath("web_app")))
    if (web_root / "index.html").is_file():
        application.mount("/", WebAppFiles(directory=web_root, html=True), name="web-app")
    return application


app = create_app()
