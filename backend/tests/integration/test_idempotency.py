import threading
from datetime import date

from sqlalchemy import func, select

from app.errors import Codes
from app.models import Dispense, DispenseAttempt
from tests.conftest import dispense_body

URL = "/api/v1/dispenses"


def test_replay_of_accepted_returns_original_and_creates_nothing(client, factory, session):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1))
    body = dispense_body(idempotency_key="key-accepted-1")
    first = client.post(URL, json=body)
    second = client.post(URL, json=body)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert session.scalar(select(func.count()).select_from(Dispense)) == 1
    assert session.scalar(select(func.count()).select_from(DispenseAttempt)) == 1


def test_replay_of_rejection_returns_original_rejection(client, factory, session):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), per=10)
    body = dispense_body(quantity=11, idempotency_key="key-rejected-1")
    first = client.post(URL, json=body)
    # Even if the rules would now allow it, the key's outcome is fixed.
    second = client.post(URL, json=body)
    assert first.status_code == second.status_code == 422
    assert first.json() == second.json()
    assert session.scalar(select(func.count()).select_from(DispenseAttempt)) == 1


def test_same_instant_in_another_offset_is_the_same_payload(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1))
    a = client.post(URL, json=dispense_body(idempotency_key="key-offset-1", dispensed_at="2026-06-15T09:00:00+02:00"))
    b = client.post(URL, json=dispense_body(idempotency_key="key-offset-1", dispensed_at="2026-06-15T07:00:00Z"))
    assert a.status_code == b.status_code == 201
    assert b.headers["Idempotent-Replayed"] == "true"


def test_reused_key_with_different_payload_is_rejected(client, factory, session):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1))
    client.post(URL, json=dispense_body(idempotency_key="key-reuse-1", quantity=1))
    res = client.post(URL, json=dispense_body(idempotency_key="key-reuse-1", quantity=2))
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == Codes.IDEMPOTENCY_KEY_REUSED
    assert body["errors"][0]["field"] == "idempotency_key"
    assert session.scalar(select(func.count()).select_from(Dispense)) == 1
    assert session.scalar(select(func.count()).select_from(DispenseAttempt)) == 1


def test_concurrent_duplicates_create_exactly_one_dispense(client, factory, session):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1))
    body = dispense_body(idempotency_key="key-race-1")
    barrier = threading.Barrier(8)
    results = []

    def go():
        barrier.wait()
        r = client.post(URL, json=body)
        results.append((r.status_code, r.headers["Idempotent-Replayed"], r.json()["id"]))

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert {s for s, _, _ in results} == {201}
    assert sorted(r for _, r, _ in results) == ["false"] + ["true"] * 7
    assert len({i for _, _, i in results}) == 1
    assert session.scalar(select(func.count()).select_from(Dispense)) == 1
