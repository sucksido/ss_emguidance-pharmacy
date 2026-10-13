from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.rules_engine import Candidate, MedicineFacts, PriorDispense, RuleFacts, evaluate
from app.errors import Codes

NOW = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
MED = MedicineFacts(id=1, code="PARA500", is_active=True)


def rule(rid=1, frm=date(2026, 1, 1), to=None, per=10, window=30, auth=False):
    return RuleFacts(rid, frm, to, per, window, auth)


def cand(qty=5, at=datetime(2026, 6, 15, 8, 0, tzinfo=UTC), auth=None):
    return Candidate("PARA500", "P1", qty, at, auth)


def codes(ev):
    return sorted(e.code for e in ev.violations)


def test_accepts_within_all_limits():
    ev = evaluate(cand(), MED, [rule()], [], NOW)
    assert ev.accepted
    assert ev.governing_rule.id == 1


def test_reports_every_violation_not_just_the_first():
    inactive = MedicineFacts(1, "PARA500", is_active=False)
    r = rule(per=10, window=12, auth=True)
    ev = evaluate(cand(qty=11), inactive, [r], [PriorDispense(date(2026, 6, 10), 5)], NOW)
    assert codes(ev) == sorted(
        [
            Codes.MEDICINE_INACTIVE,
            Codes.MAX_QUANTITY_PER_DISPENSE_EXCEEDED,
            Codes.AUTHORISATION_REQUIRED,
            Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED,
        ]
    )
    fields = {e.code: e.field for e in ev.violations}
    assert fields[Codes.MEDICINE_INACTIVE] == "medicine_code"
    assert fields[Codes.AUTHORISATION_REQUIRED] == "authorisation_ref"
    assert fields[Codes.MAX_QUANTITY_PER_DISPENSE_EXCEEDED] == "quantity"


def test_quantity_equal_to_limits_is_allowed():
    ev = evaluate(cand(qty=10), MED, [rule(per=10, window=30)], [PriorDispense(date(2026, 6, 1), 20)], NOW)
    assert ev.accepted


def test_unknown_medicine():
    ev = evaluate(cand(), None, [], [], NOW)
    assert codes(ev) == [Codes.MEDICINE_NOT_FOUND]


def test_no_rule_in_force_at_dispensed_at():
    ev = evaluate(cand(), MED, [rule(frm=date(2026, 7, 1))], [], NOW)
    assert codes(ev) == [Codes.NO_RULE_IN_FORCE]


def test_uses_rule_in_force_at_dispensed_at_not_now():
    old = rule(rid=1, frm=date(2026, 1, 1), to=date(2026, 6, 1), per=100, window=100)
    new = rule(rid=2, frm=date(2026, 6, 1), per=5)
    march = cand(qty=50, at=datetime(2026, 3, 10, 9, tzinfo=UTC))
    ev = evaluate(march, MED, [old, new], [], NOW)
    assert ev.accepted and ev.governing_rule.id == 1


def test_rule_boundary_is_local_midnight_not_utc_midnight():
    old = rule(rid=1, frm=date(2026, 1, 1), to=date(2026, 6, 1), per=100, window=100)
    new = rule(rid=2, frm=date(2026, 6, 1), per=5)
    # 22:30 UTC on 31 May is 00:30 SAST on 1 June -> the June rule governs.
    late = cand(qty=50, at=datetime(2026, 5, 31, 22, 30, tzinfo=UTC))
    ev = evaluate(late, MED, [old, new], [], NOW)
    assert ev.governing_rule.id == 2
    assert Codes.MAX_QUANTITY_PER_DISPENSE_EXCEEDED in codes(ev)
    # 21:59 UTC on 31 May is 23:59 SAST on 31 May -> still the May rule.
    ev = evaluate(cand(qty=50, at=datetime(2026, 5, 31, 21, 59, tzinfo=UTC)), MED, [old, new], [], NOW)
    assert ev.accepted and ev.governing_rule.id == 1


@pytest.mark.parametrize(
    "prior_day, counted",
    [
        (date(2026, 5, 17), True),  # 29 days before 15 June: first day of the window
        (date(2026, 5, 16), False),  # 30 days before: just outside
        (date(2026, 6, 15), True),  # same business day
    ],
)
def test_rolling_window_is_30_local_days_inclusive(prior_day, counted):
    r = rule(per=10, window=10)
    ev = evaluate(cand(qty=5), MED, [r], [PriorDispense(prior_day, 6)], NOW)
    assert (Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED in codes(ev)) is counted


def test_backdated_dispense_counts_dispenses_recorded_later_in_its_window():
    # History holds a dispense on 14 June that was recorded *before* this request,
    # but this request is backdated to 15 June; both lie in the same window.
    ev = evaluate(cand(qty=5), MED, [rule(window=10)], [PriorDispense(date(2026, 6, 14), 6)], NOW)
    assert Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED in codes(ev)


def test_backdated_dispense_may_not_break_a_later_dispense_window():
    # Existing: 10 units on 20 June (fine on its own, limit 12).
    # Candidate: 5 units backdated to 15 June -> its own window is 5 (fine),
    # but the 20 June window becomes 15 > 12.
    r = rule(per=10, window=12)
    ev = evaluate(cand(qty=5), MED, [r], [PriorDispense(date(2026, 6, 20), 10)], NOW)
    assert codes(ev) == [Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED_LATER]
    affected = ev.violations[0].meta["affected"]
    assert affected == [{"anchor_date": "2026-06-20", "rule_id": 1, "limit": 12, "total_with_candidate": 15}]


def test_later_window_is_judged_by_the_rule_in_force_on_that_later_date():
    early = rule(rid=1, frm=date(2026, 1, 1), to=date(2026, 6, 18), per=10, window=100)
    later = rule(rid=2, frm=date(2026, 6, 18), per=10, window=12)
    ev = evaluate(cand(qty=5), MED, [early, later], [PriorDispense(date(2026, 6, 20), 10)], NOW)
    assert codes(ev) == [Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED_LATER]
    assert ev.violations[0].rule_id == 2


def test_later_dispense_outside_reach_is_ignored():
    r = rule(per=10, window=12)
    # 15 June + 29 days = 14 July is the last window that contains 15 June.
    ev = evaluate(cand(qty=5), MED, [r], [PriorDispense(date(2026, 7, 15), 10)], NOW)
    assert ev.accepted


def test_authorisation_whitespace_is_not_an_authorisation():
    ev = evaluate(cand(auth="   "), MED, [rule(auth=True)], [], NOW)
    assert codes(ev) == [Codes.AUTHORISATION_REQUIRED]
    assert evaluate(cand(auth="AUTH-1"), MED, [rule(auth=True)], [], NOW).accepted


def test_future_dispense_rejected_beyond_tolerance():
    ev = evaluate(cand(at=NOW + timedelta(minutes=4)), MED, [rule()], [], NOW)
    assert ev.accepted
    ev = evaluate(cand(at=NOW + timedelta(hours=1)), MED, [rule()], [], NOW)
    assert codes(ev) == [Codes.DISPENSED_AT_IN_FUTURE]
