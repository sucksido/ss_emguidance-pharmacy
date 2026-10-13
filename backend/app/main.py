import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import dispenses, medicines
from app.config import get_settings
from app.errors import install_error_handlers

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = FastAPI(
        title="Pharmacy Formulary & Dispensing API",
        version="1.0.0",
        description="Time-versioned formulary rules and validated, idempotent dispensing.",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Idempotent-Replayed", "X-Request-ID", "Server-Timing"],
    )

    @app.middleware("http")
    async def request_id_and_timing(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - start) * 1000:.1f}"
        return response

    install_error_handlers(app)
    app.include_router(medicines.router, prefix=API_PREFIX)
    app.include_router(dispenses.router, prefix=API_PREFIX)

    @app.get(f"{API_PREFIX}/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
