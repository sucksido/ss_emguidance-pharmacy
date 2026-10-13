"""The error contract (DECISIONS.md, ADR-004).

Every non-2xx response from the API - business rejections, validation failures,
not-found, conflicts, unexpected crashes - is an RFC 9457 problem document with
two extensions:

* ``code``   - a stable, machine-readable identifier for the *overall* problem.
* ``errors`` - a list of every individual reason, each with its own ``code``,
               the request ``field`` it should be rendered against (or null when
               it is not attributable to one field), a human ``message``, the
               ``rule_id`` of the formulary rule that produced it (if any), and a
               free-form ``meta`` object with the numbers behind the decision.

A frontend therefore never has to parse ``message`` to decide where to show it.
"""

from __future__ import annotations

import logging
import dataclasses
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"
TYPE_BASE = "https://pharmacy.example/problems/"


class Codes:
    # Overall problem codes
    VALIDATION_FAILED = "VALIDATION_FAILED"
    DISPENSE_REJECTED = "DISPENSE_REJECTED"
    NOT_FOUND = "NOT_FOUND"
    MEDICINE_NOT_FOUND = "MEDICINE_NOT_FOUND"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    RULE_CONFLICT = "RULE_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # Field / reason codes
    FIELD_REQUIRED = "FIELD_REQUIRED"
    FIELD_INVALID = "FIELD_INVALID"
    INVALID_CURSOR = "INVALID_CURSOR"
    MEDICINE_INACTIVE = "MEDICINE_INACTIVE"
    NO_RULE_IN_FORCE = "NO_RULE_IN_FORCE"
    DISPENSED_AT_IN_FUTURE = "DISPENSED_AT_IN_FUTURE"
    MAX_QUANTITY_PER_DISPENSE_EXCEEDED = "MAX_QUANTITY_PER_DISPENSE_EXCEEDED"
    MAX_QUANTITY_PER_30_DAYS_EXCEEDED = "MAX_QUANTITY_PER_30_DAYS_EXCEEDED"
    MAX_QUANTITY_PER_30_DAYS_EXCEEDED_LATER = "MAX_QUANTITY_PER_30_DAYS_EXCEEDED_LATER"
    AUTHORISATION_REQUIRED = "AUTHORISATION_REQUIRED"
    RULE_ALREADY_STARTS_ON_DATE = "RULE_ALREADY_STARTS_ON_DATE"
    RULE_OVERLAPS_LATER_RULE = "RULE_OVERLAPS_LATER_RULE"
    SUPERSEDE_LEAVES_GAP = "SUPERSEDE_LEAVES_GAP"
    RETROACTIVE_RULE_CHANGE = "RETROACTIVE_RULE_CHANGE"
    RULE_PERIOD_OVERLAP = "RULE_PERIOD_OVERLAP"


@dataclass(frozen=True)
class ErrorItem:
    code: str
    message: str
    field: str | None = None
    rule_id: int | None = None
    meta: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "rule_id": self.rule_id,
            "meta": self.meta,
        }


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        errors: list[ErrorItem] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = errors or []
        self.extra = extra or {}


def problem_body(
    *,
    status: int,
    code: str,
    title: str,
    instance: str,
    detail: str | None = None,
    errors: list[ErrorItem] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": TYPE_BASE + code.lower().replace("_", "-"),
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "instance": instance,
        "errors": [e.to_dict() for e in (errors or [])],
    }
    if extra:
        body.update(extra)
    return body


def problem_response(body: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=body["status"], media_type=PROBLEM_JSON, headers=headers)


def _field_from_loc(loc: tuple[Any, ...]) -> str | None:
    # ("body", "quantity") -> "quantity"; ("query", "limit") -> "limit";
    # ("body",) (unparseable body) -> None
    parts = [str(p) for p in loc[1:]] if loc and loc[0] in ("body", "query", "path", "header") else [str(p) for p in loc]
    return ".".join(parts) or None


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return problem_response(
            problem_body(
                status=exc.status,
                code=exc.code,
                title=exc.title,
                detail=exc.detail,
                instance=request.url.path,
                errors=exc.errors,
                extra=exc.extra,
            )
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        items = []
        for err in exc.errors():
            ctx = {k: str(v) for k, v in (err.get("ctx") or {}).items()}
            items.append(
                ErrorItem(
                    code=Codes.FIELD_REQUIRED if err["type"] == "missing" else Codes.FIELD_INVALID,
                    field=_field_from_loc(tuple(err["loc"])),
                    message=err["msg"],
                    meta={"type": err["type"], **ctx},
                )
            )
        return problem_response(
            problem_body(
                status=422,
                code=Codes.VALIDATION_FAILED,
                title="Request validation failed",
                detail=f"{len(items)} field(s) failed validation",
                instance=request.url.path,
                errors=items,
            )
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = Codes.NOT_FOUND if exc.status_code == 404 else f"HTTP_{exc.status_code}"
        return problem_response(
            problem_body(
                status=exc.status_code,
                code=code,
                title=str(exc.detail),
                instance=request.url.path,
            )
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s", request.url.path)
        return problem_response(
            problem_body(
                status=500,
                code=Codes.INTERNAL_ERROR,
                title="Internal server error",
                instance=request.url.path,
            )
        )
