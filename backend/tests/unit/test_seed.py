from collections import Counter
from datetime import UTC, datetime

from app.seed import build
from app.timeutil import business_date

NOW = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)


def test_seed_meets_the_volume_brief():
    medicines, rules, dispenses, _ = build(scale=1, seed=1, today=business_date(NOW), now=NOW)
    assert len(medicines) >= 500
    per_med = Counter(r["medicine_id"] for r in rules)
    assert set(per_med.values()) <= {3, 4, 5} and len(per_med) == len(medicines)
    assert len(dispenses) >= 2000
    assert len({d["patient_ref"] for d in dispenses}) >= 2000
    days = sorted(business_date(d["dispensed_at"]) for d in dispenses)
    assert (days[-1] - days[0]).days >= 700


def test_seed_rule_periods_are_contiguous_and_non_overlapping():
    _, rules, _, _ = build(scale=1, seed=1, today=business_date(NOW), now=NOW)
    by_med: dict[int, list] = {}
    for r in rules:
        by_med.setdefault(r["medicine_id"], []).append(r)
    for rs in by_med.values():
        rs.sort(key=lambda r: r["effective_from"])
        for a, b in zip(rs, rs[1:]):
            assert a["effective_to"] == b["effective_from"]
        assert rs[-1]["effective_to"] is None


def test_seed_is_deterministic():
    a = build(scale=1, seed=5, today=business_date(NOW), now=NOW)[2]
    b = build(scale=1, seed=5, today=business_date(NOW), now=NOW)[2]
    assert a == b
