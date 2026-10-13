"""Business rule 9: simultaneous dispenses for the same patient and medicine must
not jointly breach max_quantity_per_30_days.

How these tests avoid "passing because the requests happened to serialise":

* Each request runs on its own thread with its own database connection.
* A test hook (app/testpoints.py) pauses the FIRST request *after* it has read
  the 30-day window and *before* it inserts - the exact gap a race exploits.
* While it is paused, the test polls pg_locks until it sees the SECOND request
  waiting on the (medicine, patient) advisory lock. Only then is the first
  released. So we have observed, not assumed, that both requests were in
  flight at the same time and that the second was stopped at the lock.
* A negative control disables only that lock and shows that the same
  choreography then DOES breach the limit. If someone deletes or breaks the
  lock, test_lock_is_what_prevents_the_breach keeps passing but
  test_simultaneous_dispenses_cannot_jointly_breach fails.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import date

from sqlalchemy import text

from app import db as app_db
from app import testpoints
from app.errors import ApiError, Codes
from app.schemas import DispenseIn
from app.services import dispensing
from app.timeutil import FixedClock
from tests.integration.conftest import NOW

LIMIT = 10


def _request(qty: int) -> DispenseIn:
    return DispenseIn(
        medicine_code="PARA500",
        patient_ref="PT-RACE",
        quantity=qty,
        dispensed_at="2026-06-15T09:00:00+02:00",
        idempotency_key=f"race-{uuid.uuid4()}",
    )


def _advisory_waiters() -> int:
    with app_db.get_engine().connect() as conn:
        return conn.scalar(
            text(
                "SELECT count(*) FROM pg_locks l JOIN pg_database d ON d.oid = l.database "
                "WHERE l.locktype = 'advisory' AND NOT l.granted AND d.datname = current_database()"
            )
        )


def _run(requests: list[DispenseIn]) -> list[dispensing.DispenseResult]:
    results: list[dispensing.DispenseResult | BaseException] = [None] * len(requests)  # type: ignore[list-item]

    def worker(i: int) -> None:
        with app_db.session_factory()() as s:
            try:
                results[i] = dispensing.submit_dispense(s, requests[i], clock=FixedClock(NOW), actor="t")
            except BaseException as e:  # surfaced in the main thread
                results[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(requests))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    for r in results:
        if isinstance(r, BaseException):
            raise r
    return results  # type: ignore[return-value]


def _total_dispensed() -> int:
    with app_db.get_engine().connect() as conn:
        return conn.scalar(text("SELECT coalesce(sum(quantity), 0) FROM dispenses WHERE patient_ref = 'PT-RACE'"))


def test_simultaneous_dispenses_cannot_jointly_breach(factory, monkeypatch):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), per=LIMIT, window=LIMIT)

    gate = threading.Lock()
    leader_seen = threading.Event()
    observed_second_blocked = threading.Event()

    def hook(name: str) -> None:
        if name != "dispense.after_window_read":
            return
        with gate:
            is_leader = not leader_seen.is_set()
            leader_seen.set()
        if not is_leader:
            return
        # Leader has read the window (total 0) and holds the lock. Wait until the
        # follower is demonstrably queued behind it.
        for _ in range(500):
            if _advisory_waiters() >= 1:
                observed_second_blocked.set()
                break
            time.sleep(0.01)

    monkeypatch.setattr(testpoints, "reached", hook)
    results = _run([_request(6), _request(6)])

    assert observed_second_blocked.is_set(), "requests did not overlap; the test proved nothing"
    statuses = sorted(r.status for r in results)
    assert statuses == [201, 422]
    rejected = next(r for r in results if r.status == 422)
    assert [e["code"] for e in rejected.body["errors"]] == [Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED]
    assert rejected.body["errors"][0]["meta"]["already_dispensed"] == 6
    assert _total_dispensed() == 6 <= LIMIT


def test_lock_is_what_prevents_the_breach(factory, monkeypatch):
    """Negative control: same choreography with the window lock disabled."""
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), per=LIMIT, window=LIMIT)

    both_read = threading.Barrier(2, timeout=10)
    monkeypatch.setattr(dispensing, "lock_patient_medicine", lambda *a, **k: None)
    monkeypatch.setattr(testpoints, "reached", lambda name: both_read.wait() if name == "dispense.after_window_read" else None)

    results = _run([_request(6), _request(6)])

    assert sorted(r.status for r in results) == [201, 201]
    assert _total_dispensed() == 12 > LIMIT  # the breach the lock exists to prevent


def test_many_concurrent_requests_respect_the_limit(factory):
    """Uncoordinated stress: 20 threads x 3 units against a limit of 10."""
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), per=LIMIT, window=LIMIT)
    results = _run([_request(3) for _ in range(20)])
    assert sum(1 for r in results if r.status == 201) == 3
    assert _total_dispensed() == 9


def test_different_patients_are_not_serialised_against_each_other(factory, monkeypatch):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), per=LIMIT, window=LIMIT)
    both_read = threading.Barrier(2, timeout=5)
    monkeypatch.setattr(testpoints, "reached", lambda name: both_read.wait() if name == "dispense.after_window_read" else None)
    a, b = _request(6), _request(6)
    b = b.model_copy(update={"patient_ref": "PT-OTHER"})
    # If the lock were global (or per medicine) the barrier would time out here.
    results = _run([a, b])
    assert [r.status for r in results] == [201, 201]


def _lock_waiters() -> int:
    with app_db.get_engine().connect() as conn:
        return conn.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
            )
        )


def test_supersede_cannot_slip_under_an_in_flight_dispense(factory, monkeypatch):
    """A dispense holds FOR SHARE on its medicine while it evaluates. A concurrent
    supersede (FOR UPDATE) must wait, then see the committed dispense and refuse
    to change the rule that governed it. Without the share lock the supersede
    would commit first and the dispense would be pinned to a rule whose period
    no longer covers it."""
    from app.schemas import NewRuleIn
    from app.services import formulary

    m = factory.medicine()
    rule = factory.rule(m, date(2026, 1, 1), per=LIMIT, window=LIMIT)

    supersede_blocked = threading.Event()
    in_dispense = threading.Event()

    def hook(name: str) -> None:
        if name != "dispense.after_window_read":
            return
        in_dispense.set()
        for _ in range(500):
            if _lock_waiters() >= 1:
                supersede_blocked.set()
                return
            time.sleep(0.01)

    monkeypatch.setattr(testpoints, "reached", hook)
    outcome: dict[str, object] = {}

    def do_supersede() -> None:
        in_dispense.wait(10)
        with app_db.session_factory()() as s:
            try:
                formulary.supersede(
                    s,
                    "PARA500",
                    NewRuleIn(
                        effective_from=date(2026, 6, 1),
                        max_quantity_per_dispense=1,
                        max_quantity_per_30_days=1,
                        requires_authorisation=False,
                    ),
                    clock=FixedClock(NOW),
                    actor="t",
                )
                outcome["supersede"] = "committed"
            except ApiError as e:
                outcome["supersede"] = e.errors[0].code

    t = threading.Thread(target=do_supersede)
    t.start()
    (result,) = _run([_request(5)])
    t.join(20)

    assert supersede_blocked.is_set(), "supersede never waited on the dispense; the test proved nothing"
    assert result.status == 201 and result.body["formulary_rule_id"] == rule.id
    assert outcome["supersede"] == Codes.RETROACTIVE_RULE_CHANGE
    with app_db.get_engine().connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM formulary_rules")) == 1
