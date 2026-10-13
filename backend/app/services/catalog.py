"""Read side: medicine search, rule history, dispense ledger. All listings use
keyset pagination (DECISIONS.md, ADR-003) and are served by the indexes in
migrations 0002-0004 (ADR-005)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, tuple_
from sqlalchemy.orm import Session

from app.errors import ApiError, Codes
from app.models import Dispense, DispenseAttempt, FormularyRule, Medicine
from app.pagination import decode_cursor, invalid_cursor, page_envelope
from app.schemas import AttemptOut, MedicineDetailOut, RuleHistoryOut
from app.services.presenters import dispense_out, jsonable, medicine_out, rule_out
from app.timeutil import Clock, business_date


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _medicine_or_404(session: Session, code: str) -> Medicine:
    m = session.scalar(select(Medicine).where(Medicine.code == code))
    if m is None:
        raise ApiError(404, Codes.MEDICINE_NOT_FOUND, "Medicine not found", detail=f"No medicine with code '{code}'.")
    return m


def search_medicines(session: Session, q: str | None, limit: int, cursor: str | None) -> dict[str, Any]:
    term = (q or "").strip()
    filters = {"q": term.lower()}
    stmt = select(Medicine)
    if term:
        pattern = f"%{_escape_like(term)}%"
        # ILIKE '%term%' is served by the pg_trgm GIN indexes (migration 0004).
        stmt = stmt.where(or_(Medicine.name.ilike(pattern), Medicine.code.ilike(pattern)))
    if cursor:
        name, mid = decode_cursor(cursor, filters, (str, int))
        stmt = stmt.where(tuple_(Medicine.name, Medicine.id) > tuple_(name, mid))
    rows = session.scalars(stmt.order_by(Medicine.name, Medicine.id).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    next_key = [rows[-1].name, rows[-1].id] if more else None
    return page_envelope([jsonable(medicine_out(m)) for m in rows], limit, next_key, filters)


def medicine_detail(session: Session, code: str, clock: Clock) -> MedicineDetailOut:
    m = _medicine_or_404(session, code)
    today = business_date(clock.now())
    current = session.scalar(
        select(FormularyRule).where(
            FormularyRule.medicine_id == m.id,
            FormularyRule.effective_from <= today,
            (FormularyRule.effective_to.is_(None)) | (FormularyRule.effective_to > today),
        )
    )
    return MedicineDetailOut(
        **medicine_out(m).model_dump(),
        current_rule=rule_out(current, today) if current else None,
        business_date=today,
    )


def rule_history(session: Session, code: str, clock: Clock) -> RuleHistoryOut:
    m = _medicine_or_404(session, code)
    today = business_date(clock.now())
    rules = session.scalars(
        select(FormularyRule).where(FormularyRule.medicine_id == m.id).order_by(FormularyRule.effective_from)
    ).all()
    items = [rule_out(r, today) for r in rules]
    in_force = next((i.id for i in items if i.status == "in_force"), None)
    return RuleHistoryOut(medicine_code=m.code, business_date=today, in_force_rule_id=in_force, items=items)


def list_dispenses(
    session: Session, patient_ref: str | None, medicine_code: str | None, limit: int, cursor: str | None
) -> dict[str, Any]:
    filters = {"patient_ref": patient_ref, "medicine_code": medicine_code}
    stmt = select(Dispense, Medicine).join(Medicine, Medicine.id == Dispense.medicine_id)
    if patient_ref:
        stmt = stmt.where(Dispense.patient_ref == patient_ref)
    if medicine_code:
        med = session.scalar(select(Medicine.id).where(Medicine.code == medicine_code))
        if med is None:
            return page_envelope([], limit, None, filters)
        stmt = stmt.where(Dispense.medicine_id == med)
    if cursor:
        ts, did = decode_cursor(cursor, filters, (str, int))
        try:
            ts_val = datetime.fromisoformat(ts).astimezone(UTC)
        except (TypeError, ValueError) as exc:
            raise invalid_cursor() from exc
        stmt = stmt.where(tuple_(Dispense.dispensed_at, Dispense.id) < tuple_(ts_val, did))
    rows = session.execute(stmt.order_by(Dispense.dispensed_at.desc(), Dispense.id.desc()).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    next_key = [rows[-1][0].dispensed_at.isoformat(), rows[-1][0].id] if more else None
    return page_envelope([jsonable(dispense_out(d, m)) for d, m in rows], limit, next_key, filters)


def list_attempts(
    session: Session, patient_ref: str | None, outcome: str | None, limit: int, cursor: str | None
) -> dict[str, Any]:
    filters = {"patient_ref": patient_ref, "outcome": outcome}
    stmt = select(DispenseAttempt)
    if patient_ref:
        stmt = stmt.where(DispenseAttempt.patient_ref == patient_ref)
    if outcome:
        stmt = stmt.where(DispenseAttempt.outcome == outcome)
    if cursor:
        (aid,) = decode_cursor(cursor, filters, (int,))
        stmt = stmt.where(DispenseAttempt.id < aid)
    rows = session.scalars(stmt.order_by(DispenseAttempt.id.desc()).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    next_key = [rows[-1].id] if more else None
    items = [jsonable(AttemptOut.model_validate(a, from_attributes=True)) for a in rows]
    return page_envelope(items, limit, next_key, filters)
