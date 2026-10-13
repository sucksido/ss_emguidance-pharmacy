from datetime import date

from sqlalchemy import func, select

from app.errors import Codes
from app.models import Dispense, DispenseAttempt
from tests.conftest import dispense_body

URL = "/api/v1/dispenses"


def counts(session):
    return (
        session.scalar(select(func.count()).select_from(Dispense)),
        session.scalar(select(func.count()).select_from(DispenseAttempt)),
    )


def test_accepted_dispense_is_recorded_and_pinned_to_its_rule(client, factory, session):
    m = factory.medicine()
    r = factory.rule(m, date(2026, 1, 1))
    res = client.post(URL, json=dispense_body(), headers={"X-Actor": "pharmacist-1"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["formulary_rule_id"] == r.id
    assert body["business_date"] == "2026-06-15"
    assert body["dispensed_at"].startswith("2026-06-15T07:00:00")  # stored and returned in UTC
    assert res.headers["Idempotent-Replayed"] == "false"
    assert counts(session) == (1, 1)
    attempt = session.scalar(select(DispenseAttempt))
    assert attempt.outcome == "accepted" and attempt.created_by == "pharmacist-1"


def test_rejection_reports_every_violation_against_its_field(client, factory, session):
    m = factory.medicine(active=False)
    factory.rule(m, date(2026, 1, 1), per=10, window=12, auth=True)
    res = client.post(URL, json=dispense_body(quantity=13, authorisation_ref="  "))
    assert res.status_code == 422
    assert res.headers["content-type"].startswith("application/problem+json")
    body = res.json()
    assert body["code"] == Codes.DISPENSE_REJECTED
    by_code = {e["code"]: e for e in body["errors"]}
    assert set(by_code) == {
        Codes.MEDICINE_INACTIVE,
        Codes.MAX_QUANTITY_PER_DISPENSE_EXCEEDED,
        Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED,
        Codes.AUTHORISATION_REQUIRED,
    }
    assert by_code[Codes.MEDICINE_INACTIVE]["field"] == "medicine_code"
    assert by_code[Codes.AUTHORISATION_REQUIRED]["field"] == "authorisation_ref"
    assert by_code[Codes.MAX_QUANTITY_PER_DISPENSE_EXCEEDED]["meta"] == {"limit": 10, "requested": 13}


def test_rejection_is_logged_and_leaves_no_dispense(client, factory, session):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), per=10)
    res = client.post(URL, json=dispense_body(quantity=11))
    assert res.status_code == 422
    assert counts(session) == (0, 1)
    attempt = session.scalar(select(DispenseAttempt))
    assert attempt.outcome == "rejected"
    assert attempt.reason_codes == [Codes.MAX_QUANTITY_PER_DISPENSE_EXCEEDED]
    assert attempt.dispense_id is None
    assert res.json()["attempt_id"] == attempt.id


def test_unknown_medicine_is_a_logged_rejection(client, session):
    res = client.post(URL, json=dispense_body(medicine_code="NOPE"))
    assert res.status_code == 422
    assert [e["code"] for e in res.json()["errors"]] == [Codes.MEDICINE_NOT_FOUND]
    assert counts(session) == (0, 1)


def test_validated_against_rule_in_force_at_dispensed_at(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), date(2026, 4, 1), per=50, window=100)
    factory.rule(m, date(2026, 4, 1), per=5, window=30)
    march = client.post(URL, json=dispense_body(quantity=40, dispensed_at="2026-03-15T10:00:00+02:00"))
    assert march.status_code == 201
    june = client.post(URL, json=dispense_body(quantity=40, patient_ref="PT-2"))
    assert june.status_code == 422


def test_rule_boundary_follows_johannesburg_midnight(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), date(2026, 4, 1), per=50, window=100)
    factory.rule(m, date(2026, 4, 1), per=5, window=30)
    # 22:30Z on 31 March is 00:30 on 1 April in Johannesburg -> April rule (max 5).
    res = client.post(URL, json=dispense_body(quantity=40, dispensed_at="2026-03-31T22:30:00Z"))
    assert res.status_code == 422
    assert res.json()["business_date"] == "2026-04-01"


def test_no_rule_in_force(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 7, 1))
    res = client.post(URL, json=dispense_body())
    assert [e["code"] for e in res.json()["errors"]] == [Codes.NO_RULE_IN_FORCE]
    assert res.json()["errors"][0]["field"] == "dispensed_at"


def test_rolling_limit_counts_backdated_and_later_recorded(client, factory, session):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), per=10, window=12)
    # Recorded first, occurred later (20 June).
    assert client.post(URL, json=dispense_body(quantity=10, dispensed_at="2026-06-20T10:00:00+02:00")).status_code == 201
    # Backdated to 15 June: own window is fine (5) but 20 June's window would become 15.
    res = client.post(URL, json=dispense_body(quantity=5, dispensed_at="2026-06-15T10:00:00+02:00"))
    assert res.status_code == 422
    err = res.json()["errors"][0]
    assert err["code"] == Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED_LATER
    assert err["meta"]["affected"][0]["anchor_date"] == "2026-06-20"
    # A backdated dispense that fits everywhere is accepted.
    ok = client.post(URL, json=dispense_body(quantity=2, dispensed_at="2026-06-15T10:00:00+02:00"))
    assert ok.status_code == 201
    assert counts(session)[0] == 2


def test_rolling_limit_is_per_patient_and_medicine(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), per=10, window=10)
    other = factory.medicine("IBU200")
    factory.rule(other, date(2026, 1, 1), per=10, window=10)
    assert client.post(URL, json=dispense_body(quantity=10)).status_code == 201
    assert client.post(URL, json=dispense_body(quantity=10, patient_ref="PT-2")).status_code == 201
    assert client.post(URL, json=dispense_body(quantity=10, medicine_code="IBU200")).status_code == 201
    assert client.post(URL, json=dispense_body(quantity=1)).status_code == 422


def test_future_dispense_rejected(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1))
    res = client.post(URL, json=dispense_body(dispensed_at="2026-07-30T10:00:00+02:00"))
    assert [e["code"] for e in res.json()["errors"]] == [Codes.DISPENSED_AT_IN_FUTURE]


def test_schema_errors_use_the_same_envelope_with_fields(client):
    res = client.post(
        URL,
        json={"medicine_code": "X", "patient_ref": "", "quantity": 0, "dispensed_at": "2026-06-15T09:00:00"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == Codes.VALIDATION_FAILED
    fields = {e["field"] for e in body["errors"]}
    assert {"patient_ref", "quantity", "dispensed_at", "idempotency_key"} <= fields
    assert all(e["code"] in (Codes.FIELD_INVALID, Codes.FIELD_REQUIRED) for e in body["errors"])


def test_list_dispenses_filters_newest_first_and_paginates(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2025, 1, 1), per=10, window=1000)
    for day in range(1, 8):
        assert (
            client.post(URL, json=dispense_body(quantity=1, dispensed_at=f"2026-06-0{day}T10:00:00+02:00")).status_code
            == 201
        )
    client.post(URL, json=dispense_body(quantity=1, patient_ref="OTHER"))

    seen = []
    cursor = None
    while True:
        params = {"patient_ref": "PT-0001", "limit": 3}
        if cursor:
            params["cursor"] = cursor
        page = client.get(URL, params=params).json()
        seen += [i["business_date"] for i in page["items"]]
        cursor = page["page"]["next_cursor"]
        if not cursor:
            break
    assert seen == [f"2026-06-0{d}" for d in range(7, 0, -1)]


def test_cursor_reuse_with_other_filters_is_rejected(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2025, 1, 1), per=10, window=1000)
    for _ in range(3):
        client.post(URL, json=dispense_body(quantity=1))
    cursor = client.get(URL, params={"patient_ref": "PT-0001", "limit": 1}).json()["page"]["next_cursor"]
    res = client.get(URL, params={"patient_ref": "SOMEONE-ELSE", "limit": 1, "cursor": cursor})
    assert res.status_code == 422
    assert res.json()["errors"][0] == {
        "code": Codes.INVALID_CURSOR,
        "field": "cursor",
        "message": "cursor was issued for a different set of filters",
        "rule_id": None,
        "meta": {},
    }
    assert client.get(URL, params={"cursor": "garbage"}).json()["errors"][0]["code"] == Codes.INVALID_CURSOR
