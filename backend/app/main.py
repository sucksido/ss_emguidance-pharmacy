import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import dispenses, medicines
from app.config import get_settings
from app.errors import Codes, install_error_handlers, problem_body, problem_response

API_PREFIX = "/api/v1"
log = logging.getLogger("app")


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = FastAPI(
        title="Pharmacy Formulary & Dispensing API",
        version="1.0.0",
        description="Time-versioned formulary rules and validated, idempotent dispensing.",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    @app.middleware("http")
    async def request_id_timing_and_crash_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Handled here rather than by an Exception handler: Starlette runs those
            # in its outermost middleware, where X-Request-ID and CORS headers would
            # never be added to the 500.
            log.exception("unhandled error on %s (request %s)", request.url.path, rid)
            response = problem_response(
                problem_body(
                    status=500,
                    code=Codes.INTERNAL_ERROR,
                    title="Internal server error",
                    detail=f"Quote request id {rid} when reporting this.",
                    instance=request.url.path,
                )
            )
        response.headers["X-Request-ID"] = rid
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - start) * 1000:.1f}"
        return response

    # Added last so it is the outermost layer and also decorates error responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Idempotent-Replayed", "X-Request-ID", "Server-Timing"],
    )

    install_error_handlers(app)
    app.include_router(medicines.router, prefix=API_PREFIX)
    app.include_router(dispenses.router, prefix=API_PREFIX)

    @app.get(f"{API_PREFIX}/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
