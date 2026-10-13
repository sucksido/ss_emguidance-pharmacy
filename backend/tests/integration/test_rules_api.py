import threading
import time
from datetime import date

import pytest
from psycopg import errors as pg_errors
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import db as app_db
from app.errors import Codes
from tests.integration.conftest import dispense_body


def new_rule(**kw):
    body = {
        "effective_from": "2026-07-01",
        "max_quantity_per_dispense": 20,
        "max_quantity_per_30_days": 60,
        "requires_authorisation": False,
    }
    body.update(kw)
    return body


def url(code="PARA500"):
    return f"/api/v1/medicines/{code}/rules"


def history(client, code="PARA500"):
    return [(r["effective_from"], r["effective_to"], r["status"]) for r in client.get(url(code)).json()["items"]]


def test_supersede_truncates_open_ended_rule_in_force(client, factory):
    m = factory.medicine()
    old = factory.rule(m, date(2026, 1, 1))
    res = client.post(url(), json=new_rule(effective_from="2026-07-01"), headers={"X-Actor": "formulary-admin"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["superseded_rule"]["id"] == old.id
    assert body["superseded_rule"]["effective_to"] == "2026-07-01"
    assert body["superseded_rule"]["superseded_by_id"] == body["rule"]["id"]
    assert body["rule"]["effective_to"] is None
    assert body["rule"]["status"] == "scheduled"
    assert body["rule"]["created_by"] == "formulary-admin"
    assert history(client) == [("2026-01-01", "2026-07-01", "in_force"), ("2026-07-01", None, "scheduled")]


def test_supersede_mid_period_inherits_the_superseded_end(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), date(2026, 9, 1))
    factory.rule(m, date(2026, 9, 1))
    res = client.post(url(), json=new_rule(effective_from="2026-07-15"))
    assert res.status_code == 201
    assert history(client) == [
        ("2026-01-01", "2026-07-15", "in_force"),
        ("2026-07-15", "2026-09-01", "scheduled"),
        ("2026-09-01", None, "scheduled"),
    ]


def test_supersede_that_would_leave_a_gap_is_refused(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1))
    res = client.post(url(), json=new_rule(effective_from="2026-07-01", effective_to="2026-08-01"))
    assert res.status_code == 422
    assert res.json()["errors"][0]["code"] == Codes.SUPERSEDE_LEAVES_GAP
    assert res.json()["errors"][0]["field"] == "effective_to"


def test_new_rule_cannot_run_into_a_later_rule(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 9, 1))  # only a scheduled rule; nothing in force in July
    res = client.post(url(), json=new_rule(effective_from="2026-07-01", effective_to="2026-10-01"))
    assert res.status_code == 409
    assert res.json()["errors"][0]["code"] == Codes.RULE_OVERLAPS_LATER_RULE
    # Without an explicit end it fills the gap up to the scheduled rule.
    ok = client.post(url(), json=new_rule(effective_from="2026-07-01"))
    assert ok.status_code == 201
    assert ok.json()["rule"]["effective_to"] == "2026-09-01"
    assert ok.json()["superseded_rule"] is None


def test_rule_starting_on_same_day_as_existing_is_refused(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1))
    res = client.post(url(), json=new_rule(effective_from="2026-01-01"))
    assert res.status_code == 409
    assert res.json()["code"] == Codes.RULE_CONFLICT
    assert res.json()["errors"][0]["code"] == Codes.RULE_ALREADY_STARTS_ON_DATE


def test_retroactive_change_under_existing_dispenses_is_refused(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1))
    assert client.post("/api/v1/dispenses", json=dispense_body(dispensed_at="2026-06-15T09:00:00+02:00")).status_code == 201
    res = client.post(url(), json=new_rule(effective_from="2026-06-01"))
    assert res.status_code == 409
    err = res.json()["errors"][0]
    assert err["code"] == Codes.RETROACTIVE_RULE_CHANGE and err["field"] == "effective_from"
    # From the day after the last dispense it is fine, even though that is in the past.
    assert client.post(url(), json=new_rule(effective_from="2026-06-16")).status_code == 201


def test_backdated_rule_allowed_where_no_dispense_is_affected(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1))
    assert client.post(url(), json=new_rule(effective_from="2026-03-01")).status_code == 201


def test_rule_body_validation_maps_to_fields(client, factory):
    factory.medicine()
    res = client.post(
        url(),
        json=new_rule(effective_to="2026-06-01", max_quantity_per_dispense=50, max_quantity_per_30_days=10),
    )
    assert res.status_code == 422
    assert {e["field"] for e in res.json()["errors"]} == {"effective_to", "max_quantity_per_30_days"}


def test_unknown_medicine_is_404_problem(client):
    res = client.post(url("NOPE"), json=new_rule())
    assert res.status_code == 404
    assert res.json()["code"] == Codes.MEDICINE_NOT_FOUND


def test_database_rejects_overlap_even_bypassing_the_application(factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), date(2026, 6, 1))
    with pytest.raises(IntegrityError) as exc:
        factory.rule(m, date(2026, 5, 31))
    assert isinstance(exc.value.orig, pg_errors.ExclusionViolation)
    # Adjacent (half-open) periods are not an overlap.
    factory.rule(m, date(2026, 6, 1))


def test_concurrent_overlapping_inserts_cannot_both_commit(factory):
    """Two transactions insert overlapping periods for the same medicine at the same
    time, each unable to see the other's uncommitted row. Application-level
    'check then insert' would let both through; the exclusion constraint does not."""
    m = factory.medicine()
    engine = app_db.get_engine()
    insert = text(
        "INSERT INTO formulary_rules (medicine_id, effective_from, effective_to, max_quantity_per_dispense,"
        " max_quantity_per_30_days, requires_authorisation) VALUES (:m, :f, NULL, 10, 30, false)"
    )
    a_inserted = threading.Event()
    outcomes: dict[str, str] = {}

    def tx_a():
        with engine.connect() as conn:
            conn.execute(insert, {"m": m.id, "f": date(2026, 1, 1)})
            a_inserted.set()
            # Hold the transaction open until B is provably blocked on our row; if
            # it never blocks, the test fails rather than passing by serialising.
            for _ in range(200):
                with engine.connect() as probe:
                    waiting = probe.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                            " AND wait_event_type = 'Lock' AND query LIKE 'INSERT INTO formulary_rules%'"
                        )
                    )
                if waiting:
                    outcomes["b_observed_blocked"] = "yes"
                    break
                time.sleep(0.02)
            conn.commit()
            outcomes["a"] = "committed"

    def tx_b():
        a_inserted.wait()
        try:
            with engine.connect() as conn:
                conn.execute(insert, {"m": m.id, "f": date(2026, 3, 1)})
                conn.commit()
                outcomes["b"] = "committed"
        except IntegrityError as e:
            outcomes["b"] = type(e.orig).__name__

    ta, tb = threading.Thread(target=tx_a), threading.Thread(target=tx_b)
    ta.start()
    tb.start()
    ta.join(10)
    tb.join(10)
    assert outcomes == {"a": "committed", "b": "ExclusionViolation", "b_observed_blocked": "yes"}
