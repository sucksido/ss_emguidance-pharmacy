"""Opaque keyset cursors (DECISIONS.md, ADR-003).

A cursor carries the sort key of the last row on the page plus a short hash of
the filters that produced it. Re-using a cursor with different filters is a
client bug and is rejected rather than silently returning a nonsensical page.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from app.errors import ApiError, Codes, ErrorItem


def filters_fingerprint(filters: dict[str, Any]) -> str:
    raw = json.dumps(filters, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def encode_cursor(key: list[Any], filters: dict[str, Any]) -> str:
    payload = json.dumps({"k": key, "f": filters_fingerprint(filters)}, default=str, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def invalid_cursor(msg: str = "cursor is malformed") -> ApiError:
    return ApiError(
        422,
        Codes.VALIDATION_FAILED,
        "Request validation failed",
        errors=[ErrorItem(code=Codes.INVALID_CURSOR, field="cursor", message=msg)],
    )


def decode_cursor(cursor: str, filters: dict[str, Any], arity: int) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        key = data["k"]
        fp = data["f"]
    except Exception as exc:  # noqa: BLE001 - any decoding failure means "not our cursor"
        raise invalid_cursor("cursor is malformed") from exc
    if not isinstance(key, list) or len(key) != arity:
        raise invalid_cursor("cursor is malformed")
    if fp != filters_fingerprint(filters):
        raise invalid_cursor("cursor was issued for a different set of filters")
    return key


def page_envelope(items: list[Any], limit: int, next_key: list[Any] | None, filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": items,
        "page": {
            "limit": limit,
            "has_more": next_key is not None,
            "next_cursor": encode_cursor(next_key, filters) if next_key is not None else None,
        },
    }
