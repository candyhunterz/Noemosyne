"""Noemosyne FastAPI application factory."""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from noemosyne_domain.errors import ConflictError, DomainError, NotFoundError
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from .routes import router


def create_app() -> FastAPI:
    """Create the API with a versioned OpenAPI contract and RFC 9457 errors."""
    environment = os.environ.get("NOEMOSYNE_ENV", "development")
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        provider = TracerProvider()
        if os.environ.get("NOEMOSYNE_OTEL_EXPORTER", "none") == "console":
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
    app = FastAPI(
        title="Noemosyne API",
        version="0.1.0",
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs" if environment == "development" else None,
        redoc_url=None,
    )
    app.include_router(router)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
        status = 400
        title = "Domain invariant violated"
        if isinstance(error, NotFoundError):
            status, title = 404, "Not found"
        elif isinstance(error, ConflictError):
            status, title = 409, "Conflict"
        return JSONResponse(
            status_code=status,
            media_type="application/problem+json",
            content={
                "type": f"https://noemosyne.dev/problems/{error.code}",
                "title": title,
                "status": status,
                "detail": error.detail,
                "code": error.code,
                "instance": str(request.url.path),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "https://noemosyne.dev/problems/request.validation_failed",
                "title": "Request validation failed",
                "status": 422,
                "detail": "Request body or parameters did not match the public contract",
                "code": "request.validation_failed",
                "instance": str(request.url.path),
            },
        )

    return app


app = create_app()
