"""Hostile or out-of-range input must produce a 422 in the error contract, never a 500."""

import base64
import json
import pytest

from app.errors import Codes
from app.pagination import filters_fingerprint
from app.services import catalog
from tests.integration.conftest import dispense_body


@pytest.mark.parametrize(
    "ts", ["0001-01-01T00:30:00+02:00", "0001-01-03T00:30:00Z", "9999-12-31T23:30:00-02:00", "1899-12-31T10:00:00Z"]
)
def test_extreme_dispensed_at_is_a_field_error(client, ts):
    res = client.post("/api/v1/dispenses", json=dispense_body(dispensed_at=ts))
    assert res.status_code == 422
    assert [e["field"] for e in res.json()["errors"]] == ["dispensed_at"]


def test_extreme_rule_dates_are_field_errors(client, factory):
    factory.medicine()
    body = {
        "effective_from": "0001-01-01",
        "effective_to": "9999-12-31",
        "max_quantity_per_dispense": 1,
        "max_quantity_per_30_days": 1,
        "requires_authorisation": False,
    }
    res = client.post("/api/v1/medicines/PARA500/rules", json=body)
    assert res.status_code == 422
    assert {e["field"] for e in res.json()["errors"]} == {"effective_from", "effective_to"}


@pytest.mark.parametrize(
    "path, params",
    [
        ("/api/v1/medicines", {"q": "a\x00b"}),
        ("/api/v1/dispenses", {"patient_ref": "P\x00"}),
        ("/api/v1/medicines/A%00B", {}),
    ],
)
def test_nul_in_query_or_path_is_a_422(client, path, params):
    res = client.get(path, params=params)
    assert res.status_code == 422
    assert res.json()["code"] == Codes.VALIDATION_FAILED


def test_nul_in_body_is_a_field_error(client):
    res = client.post("/api/v1/dispenses", json=dispense_body(patient_ref="P\x00X"))
    assert res.status_code == 422
    assert [e["field"] for e in res.json()["errors"]] == ["patient_ref"]


def _forge(key, filters):
    raw = json.dumps({"k": key, "f": filters_fingerprint(filters)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.parametrize(
    "path, key, filters",
    [
        ("/api/v1/dispenses", ["2026-01-01T00:00:00+00:00", "abc"], {"patient_ref": None, "medicine_code": None}),
        ("/api/v1/dispenses", ["not-a-date", 1], {"patient_ref": None, "medicine_code": None}),
        ("/api/v1/medicines", [1, "x"], {"q": ""}),
        ("/api/v1/medicines", ["a", True], {"q": ""}),
        ("/api/v1/dispense-attempts", ["x"], {"patient_ref": None, "outcome": None}),
    ],
)
def test_forged_cursor_with_valid_filter_hash_is_a_422(client, path, key, filters):
    res = client.get(path, params={"cursor": _forge(key, filters)})
    assert res.status_code == 422
    assert res.json()["errors"][0]["code"] == Codes.INVALID_CURSOR


def test_500_is_a_problem_document_with_request_id(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(catalog, "search_medicines", boom)
    res = client.get("/api/v1/medicines", headers={"X-Request-ID": "req-123", "Origin": "http://localhost:4200"})
    assert res.status_code == 500
    assert res.headers["content-type"].startswith("application/problem+json")
    assert res.json()["code"] == Codes.INTERNAL_ERROR
    assert "simulated" not in res.text  # internals are logged, not leaked
    assert res.headers["X-Request-ID"] == "req-123"
    assert res.headers["access-control-allow-origin"] == "http://localhost:4200"


def test_cursor_from_one_listing_is_unusable_on_another(client, factory):
    for i in range(3):
        factory.medicine(f"M{i}")
    cur = client.get("/api/v1/medicines", params={"limit": 1}).json()["page"]["next_cursor"]
    assert client.get("/api/v1/dispenses", params={"cursor": cur}).status_code == 422
