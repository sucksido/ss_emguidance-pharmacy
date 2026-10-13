from datetime import date

from app.errors import Codes


def test_search_by_partial_name_or_code_case_insensitive(client, factory):
    factory.medicine("AMOX250", name="Amoxicillin 250 mg capsule")
    factory.medicine("PARA500", name="Paracetamol 500 mg tablet")
    factory.medicine("IBU200", name="Ibuprofen 200 mg tablet")
    names = lambda q: [i["code"] for i in client.get("/api/v1/medicines", params={"q": q}).json()["items"]]  # noqa: E731
    assert names("cetam") == ["PARA500"]
    assert names("ibu2") == ["IBU200"]
    assert names("TABLET") == ["IBU200", "PARA500"]  # ordered by name
    assert names("") == ["AMOX250", "IBU200", "PARA500"]


def test_search_treats_like_wildcards_literally(client, factory):
    factory.medicine("A_1", name="Alpha")
    factory.medicine("AB1", name="Beta")
    res = client.get("/api/v1/medicines", params={"q": "a_"}).json()
    assert [i["code"] for i in res["items"]] == ["A_1"]


def test_search_paginates_without_gaps_or_duplicates(client, factory):
    for i in range(25):
        factory.medicine(f"M{i:03d}", name=f"Drug {i % 5}")  # duplicate names: tie-break on id
    codes, cursor = [], None
    while True:
        params = {"limit": 7, **({"cursor": cursor} if cursor else {})}
        page = client.get("/api/v1/medicines", params=params).json()
        codes += [i["code"] for i in page["items"]]
        cursor = page["page"]["next_cursor"]
        if not cursor:
            break
    assert len(codes) == 25 and len(set(codes)) == 25


def test_detail_includes_rule_in_force_today(client, factory):
    m = factory.medicine()
    factory.rule(m, date(2026, 1, 1), date(2026, 6, 30))
    current = factory.rule(m, date(2026, 6, 30), date(2026, 8, 1))
    factory.rule(m, date(2026, 8, 1))
    body = client.get("/api/v1/medicines/PARA500").json()
    assert body["business_date"] == "2026-06-30"
    assert body["current_rule"]["id"] == current.id
    hist = client.get("/api/v1/medicines/PARA500/rules").json()
    assert hist["in_force_rule_id"] == current.id
    assert [r["status"] for r in hist["items"]] == ["past", "in_force", "scheduled"]


def test_detail_without_rule_in_force(client, factory):
    factory.medicine()
    assert client.get("/api/v1/medicines/PARA500").json()["current_rule"] is None


def test_unknown_medicine_404(client):
    res = client.get("/api/v1/medicines/NOPE")
    assert res.status_code == 404
    assert res.json()["code"] == Codes.MEDICINE_NOT_FOUND
    assert client.get("/api/v1/nowhere").json()["code"] == Codes.NOT_FOUND
