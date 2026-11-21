"""FastAPI application factory (Phase 1).

Wires: API routes, request-id envelope, domain error mapping, SQLite + file
version store, renderer subprocess bridge, LLM adapter factory, and the
static frontend (Phase 1 minimal admin console, no canvas).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import diagrams as diagrams_api
from app.api import imports as imports_api
from app.api import patches as patches_api
from app.config import get_settings
from app.llm.adapter import build_adapter
from app.schemas.api import ApiException, ApiError, ApiErrorBody, ErrorCode, new_request_id
from app.services.renderer import RendererService
from app.storage.db import Database
from app.storage.versions import VersionStore


def create_app(settings=None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()

    app = FastAPI(title="AI Diagram Studio", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.db = Database(settings.database_path)
    app.state.version_store = VersionStore(settings.storage_root, app.state.db)
    app.state.renderer = RendererService(
        cli_path=settings.renderer_cli,
        icons_dir=settings.icons_dir if settings.icons_dir.is_dir() else None,
        timeout_seconds=settings.renderer_timeout_seconds,
        output_limit_bytes=settings.renderer_output_limit_bytes,
    )
    app.state.llm_adapter_factory = build_adapter

    @app.middleware("http")
    async def envelope_middleware(request: Request, call_next):
        request.state.requestId = new_request_id()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.requestId
        return response

    def _envelope(request: Request, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"requestId": getattr(request.state, "requestId", new_request_id()), "data": data}

    @app.exception_handler(ApiException)
    async def domain_error_handler(request: Request, exc: ApiException) -> JSONResponse:
        body = ApiError(
            requestId=getattr(request.state, "requestId", new_request_id()),
            error=ApiErrorBody(code=exc.code, message=exc.message, details=exc.details or None),
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = ApiError(
            requestId=getattr(request.state, "requestId", new_request_id()),
            error=ApiErrorBody(
                code=ErrorCode.SCHEMA_INVALID,
                message="request body failed validation",
                details={"errors": [e.get("msg", str(e)) for e in exc.errors()][:10]},
            ),
        )
        return JSONResponse(status_code=400, content=body.model_dump())

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        body = ApiError(
            requestId=getattr(request.state, "requestId", new_request_id()),
            error=ApiErrorBody(code=ErrorCode.INTERNAL_ERROR, message=f"unexpected error: {type(exc).__name__}"),
        )
        return JSONResponse(status_code=500, content=body.model_dump())

    @app.get("/health")
    async def root_health(request: Request) -> Dict[str, Any]:
        return {"status": "ok", "rendererAvailable": app.state.renderer.available()}

    app.include_router(diagrams_api.router)
    app.include_router(imports_api.router)
    app.include_router(patches_api.router)

    # Static frontend (built React admin console) — mounted last so /api and
    # /health take precedence. Missing dist simply omits the UI.
    frontend_dist: Path = settings.frontend_dist
    if (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
