"""POST /medicines/{code}/rules - introducing a rule that supersedes what is in force.

Semantics (DECISIONS.md, ADR-001):

* Periods are half-open local-date ranges ``[effective_from, effective_to)``.
* Let D be the new rule's effective_from and C the rule covering D (if any).
  - If C starts exactly on D, the request is refused (409): we do not rewrite
    or delete history; a rule that has never been in force could be amended by
    a separate, explicit operation (not built).
  - Otherwise C is *truncated* to end on D and marked ``superseded_by`` the new
    rule. Nothing else about C changes: its limits are history.
* The new rule's end defaults to C's original end, so a supersede never opens a
  gap. An explicit earlier end that would leave a gap is refused (422). If
  there is no C, the end defaults to the start of the next scheduled rule, or
  open-ended if there is none.
* The new period may not run into a later scheduled rule (409).
* A rule may not change which rule governs a dispense that already exists
  (409 RETROACTIVE_RULE_CHANGE). Backdated *rules* are allowed only where no
  dispense has yet been recorded in the affected period - this is what keeps
  "a dispense in March is governed by the rules in force in March" true after
  the fact.

Concurrency: the medicine row is locked FOR UPDATE for the whole operation,
which serialises supersedes per medicine and excludes concurrent dispenses
(they hold FOR SHARE on the same row). The GiST exclusion constraint is the
final guarantee; if it ever fires we translate it into a 409 rather than a 500.
"""

from __future__ import annotations

from datetime import date

from psycopg import errors as pg_errors
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError, Codes, ErrorItem
from app.models import Dispense, FormularyRule, Medicine
from app.schemas import NewRuleIn, SupersedeOut
from app.services.presenters import rule_out
from app.timeutil import Clock, business_date, start_of_business_day_utc


def _conflict(code: str, field: str, message: str, **meta: object) -> ApiError:
    return ApiError(
        409,
        Codes.RULE_CONFLICT,
        "Rule conflicts with existing formulary history",
        detail=message,
        errors=[ErrorItem(code=code, field=field, message=message, meta=dict(meta))],
    )


def supersede(session: Session, code: str, req: NewRuleIn, *, clock: Clock, actor: str | None) -> SupersedeOut:
    medicine = session.scalar(select(Medicine).where(Medicine.code == code).with_for_update())
    if medicine is None:
        raise ApiError(404, Codes.MEDICINE_NOT_FOUND, "Medicine not found", detail=f"No medicine with code '{code}'.")

    d = req.effective_from
    rules = session.scalars(
        select(FormularyRule).where(FormularyRule.medicine_id == medicine.id).order_by(FormularyRule.effective_from)
    ).all()
    current = next((r for r in rules if r.covers(d)), None)
    following = next((r for r in rules if r.effective_from > d), None)

    if current is not None and current.effective_from == d:
        raise _conflict(
            Codes.RULE_ALREADY_STARTS_ON_DATE,
            "effective_from",
            f"Rule {current.id} already starts on {d.isoformat()}; history is not rewritten.",
            conflicting_rule_id=current.id,
        )

    # Resolve the new rule's end.
    new_to: date | None
    if current is not None:
        if req.effective_to is not None and (current.effective_to is None or req.effective_to < current.effective_to):
            raise ApiError(
                422,
                Codes.VALIDATION_FAILED,
                "Request validation failed",
                errors=[
                    ErrorItem(
                        code=Codes.SUPERSEDE_LEAVES_GAP,
                        field="effective_to",
                        message=(
                            "A superseding rule must cover the rest of the period it replaces "
                            f"(rule {current.id} runs to "
                            f"{current.effective_to.isoformat() if current.effective_to else 'open-ended'}). "
                            "Omit effective_to to inherit it."
                        ),
                        rule_id=current.id,
                        meta={
                            "superseded_effective_to": current.effective_to.isoformat()
                            if current.effective_to
                            else None
                        },
                    )
                ],
            )
        new_to = req.effective_to if req.effective_to is not None else current.effective_to
    else:
        new_to = req.effective_to if req.effective_to is not None else (following.effective_from if following else None)

    if following is not None and (new_to is None or new_to > following.effective_from):
        raise _conflict(
            Codes.RULE_OVERLAPS_LATER_RULE,
            "effective_to",
            f"The new period would overlap rule {following.id}, which starts on "
            f"{following.effective_from.isoformat()}.",
            conflicting_rule_id=following.id,
            conflicting_effective_from=following.effective_from.isoformat(),
        )

    # Would any existing dispense change governing rule?
    lo = start_of_business_day_utc(d)
    q = select(Dispense.dispensed_at).where(Dispense.medicine_id == medicine.id, Dispense.dispensed_at >= lo)
    if new_to is not None:
        q = q.where(Dispense.dispensed_at < start_of_business_day_utc(new_to))
    first_affected = session.scalar(q.order_by(Dispense.dispensed_at).limit(1))
    if first_affected is not None:
        raise _conflict(
            Codes.RETROACTIVE_RULE_CHANGE,
            "effective_from",
            "Dispenses have already been recorded under the rules this change would replace "
            f"(earliest on {business_date(first_affected).isoformat()}).",
            earliest_affected_dispensed_at=first_affected.isoformat(),
        )

    today = business_date(clock.now())
    try:
        if current is not None:
            current.effective_to = d
            session.flush()  # shrink first, so the insert below never transiently overlaps
        new_rule = FormularyRule(
            medicine_id=medicine.id,
            effective_from=d,
            effective_to=new_to,
            max_quantity_per_dispense=req.max_quantity_per_dispense,
            max_quantity_per_30_days=req.max_quantity_per_30_days,
            requires_authorisation=req.requires_authorisation,
            created_at=clock.now(),
            created_by=actor,
        )
        session.add(new_rule)
        session.flush()
        if current is not None:
            current.superseded_by_id = new_rule.id
            session.flush()
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if isinstance(exc.orig, pg_errors.ExclusionViolation):
            raise _conflict(
                Codes.RULE_PERIOD_OVERLAP,
                "effective_from",
                "The rule period overlaps another rule for this medicine.",
            ) from exc
        raise

    return SupersedeOut(
        rule=rule_out(new_rule, today),
        superseded_rule=rule_out(current, today) if current is not None else None,
    )
