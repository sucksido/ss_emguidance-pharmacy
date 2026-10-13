"""Formulary rule evaluation - pure functions, no I/O.

This module is the only place that decides whether a dispense is allowed. The
service layer (app/services/dispensing.py) is responsible for loading the facts
below under the right locks; this module is responsible for judging them. That
split is what lets the decision logic be unit-tested exhaustively without a
database, and lets the seed script generate data that obeys the same rules.

Business dates are Africa/Johannesburg calendar dates (see app/timeutil.py).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.errors import Codes, ErrorItem
from app.timeutil import ROLLING_WINDOW_DAYS, business_date, rolling_window


@dataclass(frozen=True)
class RuleFacts:
    id: int
    effective_from: date
    effective_to: date | None  # exclusive; None = open-ended
    max_quantity_per_dispense: int
    max_quantity_per_30_days: int
    requires_authorisation: bool

    def covers(self, d: date) -> bool:
        return self.effective_from <= d and (self.effective_to is None or d < self.effective_to)


@dataclass(frozen=True)
class MedicineFacts:
    id: int
    code: str
    is_active: bool


@dataclass(frozen=True)
class PriorDispense:
    """An existing dispense for the same (patient_ref, medicine)."""

    business_date: date
    quantity: int


@dataclass(frozen=True)
class Candidate:
    medicine_code: str
    patient_ref: str
    quantity: int
    dispensed_at: datetime  # aware
    authorisation_ref: str | None


@dataclass
class Evaluation:
    business_date: date
    governing_rule: RuleFacts | None
    violations: list[ErrorItem] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.violations


def rule_in_force(rules: Iterable[RuleFacts], on: date) -> RuleFacts | None:
    # The database guarantees at most one match (exclusion constraint).
    return next((r for r in rules if r.covers(on)), None)


def history_horizon(on: date) -> tuple[date, date]:
    """Local-date range of prior dispenses the evaluation needs to see.

    Backwards: the candidate's own window. Forwards: every later dispense whose
    window would contain the candidate (rule 3 applied to a backdated dispense).
    """
    return on - timedelta(days=ROLLING_WINDOW_DAYS - 1), on + timedelta(days=ROLLING_WINDOW_DAYS - 1)


def evaluate(
    candidate: Candidate,
    medicine: MedicineFacts | None,
    rules: Sequence[RuleFacts],
    history: Sequence[PriorDispense],
    now: datetime,
    future_tolerance: timedelta = timedelta(minutes=5),
) -> Evaluation:
    """Collect *every* violation (business rule 6) rather than stopping at the first."""
    on = business_date(candidate.dispensed_at)
    v: list[ErrorItem] = []

    if candidate.dispensed_at > now + future_tolerance:
        v.append(
            ErrorItem(
                code=Codes.DISPENSED_AT_IN_FUTURE,
                field="dispensed_at",
                message="A dispense cannot be recorded for a time in the future.",
                meta={"dispensed_at": candidate.dispensed_at.isoformat(), "server_time": now.isoformat()},
            )
        )

    if medicine is None:
        v.append(
            ErrorItem(
                code=Codes.MEDICINE_NOT_FOUND,
                field="medicine_code",
                message=f"No medicine with code '{candidate.medicine_code}'.",
            )
        )
        return Evaluation(on, None, v)

    if not medicine.is_active:
        v.append(
            ErrorItem(
                code=Codes.MEDICINE_INACTIVE,
                field="medicine_code",
                message=f"Medicine {medicine.code} is inactive and may not be dispensed.",
            )
        )

    rule = rule_in_force(rules, on)
    if rule is None:
        v.append(
            ErrorItem(
                code=Codes.NO_RULE_IN_FORCE,
                field="dispensed_at",
                message=f"No formulary rule for {medicine.code} is in force on {on.isoformat()}.",
                meta={"business_date": on.isoformat()},
            )
        )
        # Every remaining check needs a rule; there is nothing further to evaluate.
        return Evaluation(on, None, v)

    if candidate.quantity > rule.max_quantity_per_dispense:
        v.append(
            ErrorItem(
                code=Codes.MAX_QUANTITY_PER_DISPENSE_EXCEEDED,
                field="quantity",
                rule_id=rule.id,
                message=(
                    f"Quantity {candidate.quantity} exceeds the maximum of "
                    f"{rule.max_quantity_per_dispense} per dispense."
                ),
                meta={"limit": rule.max_quantity_per_dispense, "requested": candidate.quantity},
            )
        )

    if rule.requires_authorisation and not (candidate.authorisation_ref or "").strip():
        v.append(
            ErrorItem(
                code=Codes.AUTHORISATION_REQUIRED,
                field="authorisation_ref",
                rule_id=rule.id,
                message="This medicine requires an authorisation reference.",
            )
        )

    # Daily totals of prior dispenses, keyed by business date.
    per_day: dict[date, int] = defaultdict(int)
    for p in history:
        per_day[p.business_date] += p.quantity

    def window_total(anchor: date) -> int:
        start, end = rolling_window(anchor)
        return sum(q for d, q in per_day.items() if start <= d <= end) + candidate.quantity

    # (a) The candidate's own window: the 30 days ending on its business date.
    own_total = window_total(on)
    if own_total > rule.max_quantity_per_30_days:
        start, end = rolling_window(on)
        v.append(
            ErrorItem(
                code=Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED,
                field="quantity",
                rule_id=rule.id,
                message=(
                    f"This dispense would bring the 30-day total to {own_total}, above the limit of "
                    f"{rule.max_quantity_per_30_days} ({start.isoformat()} to {end.isoformat()})."
                ),
                meta={
                    "limit": rule.max_quantity_per_30_days,
                    "already_dispensed": own_total - candidate.quantity,
                    "requested": candidate.quantity,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                },
            )
        )

    # (b) Later dispenses whose window now contains this (backdated) candidate.
    # Each is judged against the rule in force on *its own* date.
    affected = []
    for anchor in sorted(d for d in per_day if on < d <= on + timedelta(days=ROLLING_WINDOW_DAYS - 1)):
        anchor_rule = rule_in_force(rules, anchor)
        if anchor_rule is None:
            continue
        total = window_total(anchor)
        if total > anchor_rule.max_quantity_per_30_days:
            affected.append(
                {
                    "anchor_date": anchor.isoformat(),
                    "rule_id": anchor_rule.id,
                    "limit": anchor_rule.max_quantity_per_30_days,
                    "total_with_candidate": total,
                }
            )
    if affected:
        first = affected[0]
        v.append(
            ErrorItem(
                code=Codes.MAX_QUANTITY_PER_30_DAYS_EXCEEDED_LATER,
                field="quantity",
                rule_id=first["rule_id"],
                message=(
                    f"This backdated dispense would push the 30-day total for an existing dispense on "
                    f"{first['anchor_date']} to {first['total_with_candidate']}, above its limit of "
                    f"{first['limit']}" + (f" (and {len(affected) - 1} more)." if len(affected) > 1 else ".")
                ),
                meta={"affected": affected},
            )
        )

    return Evaluation(on, rule, v)
