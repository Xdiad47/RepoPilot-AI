"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import Container, build_container
from app.api.routes import VERSION, router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, RateLimited
from app.core.logging import configure_logging
from app.services.repository_service import purge_stale_workspaces

logger = logging.getLogger("repopilot")


class BodySizeLimitMiddleware:
    """Reject oversized request bodies before they are parsed (Content-Length and streamed bodies)."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            return await self._reject(scope, receive, send)

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope, receive, send):
        response = JSONResponse(
            {"error": {"code": "request_too_large", "message": f"Request body exceeds {self.max_bytes} bytes."}},
            status_code=413,
        )
        await response(scope, receive, send)


class _TooLarge(Exception):
    pass


def create_app(
    settings: Settings | None = None, container_factory: Callable[[Settings], Container] = build_container
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging([settings.llm_api_key, settings.github_token])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.workspace_root.mkdir(parents=True, exist_ok=True)
        removed = purge_stale_workspaces(settings.workspace_root)
        if removed:
            logger.info("Removed %d stale workspace(s) left by a previous run", removed)
        container: Container = container_factory(settings)
        app.state.container = container
        logger.info(
            "RepoPilot AI %s started (llm_configured=%s, sandbox_enabled=%s)",
            VERSION, settings.llm_configured, settings.sandbox_enabled,
        )
        yield
        await container.manager.shutdown()

    app = FastAPI(
        title="RepoPilot AI",
        version=VERSION,
        description="Evidence-based AI code repair for public GitHub repositories.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID"],
        max_age=600,
    )
    app.include_router(router)

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError):
        headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status_code, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError):
        fields: dict[str, str] = {}
        for err in exc.errors():
            name = str(err["loc"][-1]) if err.get("loc") else "body"
            fields.setdefault(name, str(err.get("msg", "invalid")).removeprefix("Value error, "))
        return JSONResponse(
            {"error": {"code": "validation_error", "message": next(iter(fields.values()), "Invalid request."), "fields": fields}},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse({"error": {"code": code, "message": str(exc.detail)}}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception):
        logger.exception("Unhandled error")
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "An unexpected server error occurred."}}, status_code=500
        )

    return app


app = create_app()
