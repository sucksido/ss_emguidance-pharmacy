"""POST /dispenses - the transactional shell around the pure rule engine.

One request == one database transaction. In order, it:

1. takes a transaction-scoped advisory lock on the idempotency key, so two
   concurrent requests with the same key cannot both pass the "not seen yet"
   check;
2. replays the stored outcome if the key has been seen (or rejects a key that
   is being reused for a different payload);
3. locks the medicine row FOR SHARE, so a concurrent rule supersede or
   activation change cannot slip in under the evaluation;
4. takes a transaction-scoped advisory lock on (medicine, patient_ref), which
   serialises the read-evaluate-insert of the rolling 30-day check for exactly
   the pairs that can conflict (DECISIONS.md, ADR-002);
5. loads the facts, asks app.domain.rules_engine for a verdict, and writes
   EITHER (dispense + accepted attempt) OR (rejected attempt only), then
   commits. Both rows go in the same commit, so an accepted attempt can never
   exist without its dispense, and a rejection can never leave a dispense
   behind (business rule 7).

Lock order is always: idempotency key -> medicine row -> (medicine, patient).
The supersede path only takes the medicine row lock, so no cycle exists.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import testpoints
from app.config import get_settings
from app.domain import rules_engine as engine
from app.errors import ApiError, Codes, ErrorItem, problem_body
from app.models import Dispense, DispenseAttempt, FormularyRule, Medicine
from app.schemas import DispenseIn
from app.services.presenters import dispense_out, jsonable
from app.timeutil import Clock, business_date, to_utc, utc_bounds

INSTANCE = "/api/v1/dispenses"


@dataclass(frozen=True)
class DispenseResult:
    status: int
    body: dict[str, Any]
    replayed: bool


def canonical_payload(req: DispenseIn) -> dict[str, Any]:
    """The request as the business sees it. Two requests that mean the same thing
    (e.g. the same instant written with different UTC offsets) have the same
    canonical form and therefore the same fingerprint."""
    auth = (req.authorisation_ref or "").strip() or None
    return {
        "medicine_code": req.medicine_code,
        "patient_ref": req.patient_ref,
        "quantity": req.quantity,
        "dispensed_at": to_utc(req.dispensed_at).isoformat(),
        "authorisation_ref": auth,
    }


def fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _lock(session: Session, namespace: str, key: str) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"{namespace}:{key}"},
    )


def lock_idempotency_key(session: Session, key: str) -> None:
    _lock(session, "dispense-idem", key)


def lock_patient_medicine(session: Session, medicine_id: int, patient_ref: str) -> None:
    _lock(session, "dispense-window", f"{medicine_id}:{patient_ref}")


def _load_facts(
    session: Session, medicine: Medicine, patient_ref: str, on: Any
) -> tuple[list[engine.RuleFacts], list[engine.PriorDispense]]:
    lo_day, hi_day = engine.history_horizon(on)
    lo, hi = utc_bounds(lo_day, hi_day)
    rows = session.execute(
        select(Dispense.dispensed_at, Dispense.quantity).where(
            Dispense.medicine_id == medicine.id,
            Dispense.patient_ref == patient_ref,
            Dispense.dispensed_at >= lo,
            Dispense.dispensed_at < hi,
        )
    ).all()
    history = [engine.PriorDispense(business_date(ts), q) for ts, q in rows]

    rules = session.scalars(
        select(FormularyRule).where(
            FormularyRule.medicine_id == medicine.id,
            FormularyRule.effective_from <= hi_day,
            (FormularyRule.effective_to.is_(None)) | (FormularyRule.effective_to > on),
        )
    ).all()
    facts = [
        engine.RuleFacts(
            r.id,
            r.effective_from,
            r.effective_to,
            r.max_quantity_per_dispense,
            r.max_quantity_per_30_days,
            r.requires_authorisation,
        )
        for r in rules
    ]
    return facts, history


def submit_dispense(session: Session, req: DispenseIn, *, clock: Clock, actor: str | None) -> DispenseResult:
    for attempt_no in range(2):
        try:
            return _submit_once(session, req, clock=clock, actor=actor)
        except IntegrityError as exc:
            session.rollback()
            # The advisory lock makes this unreachable in normal operation; the
            # unique constraint is the backstop. Retrying once turns a lost race
            # into a clean replay of the winner's outcome.
            if attempt_no == 1 or "idempotency_key" not in str(exc.orig):
                raise
    raise AssertionError("unreachable")


def _submit_once(session: Session, req: DispenseIn, *, clock: Clock, actor: str | None) -> DispenseResult:
    payload = canonical_payload(req)
    fp = fingerprint(payload)

    lock_idempotency_key(session, req.idempotency_key)

    previous = session.scalar(select(DispenseAttempt).where(DispenseAttempt.idempotency_key == req.idempotency_key))
    if previous is not None:
        # Read everything we need before ending the transaction (rollback expires ORM state).
        prev_id, prev_fp = previous.id, previous.request_fingerprint
        prev_status, prev_body = previous.http_status, previous.response_body
        session.rollback()
        if prev_fp != fp:
            raise ApiError(
                422,
                Codes.IDEMPOTENCY_KEY_REUSED,
                "Idempotency key reused with a different payload",
                detail=(
                    "This idempotency_key was already used for a different dispense request. "
                    "Generate a new key for a new request."
                ),
                errors=[
                    ErrorItem(
                        code=Codes.IDEMPOTENCY_KEY_REUSED,
                        field="idempotency_key",
                        message="Key already used for a different payload.",
                        meta={"original_attempt_id": prev_id},
                    )
                ],
            )
        return DispenseResult(prev_status, prev_body, replayed=True)

    medicine = session.scalar(select(Medicine).where(Medicine.code == req.medicine_code).with_for_update(read=True))
    on = business_date(req.dispensed_at)

    rules: list[engine.RuleFacts] = []
    history: list[engine.PriorDispense] = []
    if medicine is not None:
        lock_patient_medicine(session, medicine.id, req.patient_ref)
        rules, history = _load_facts(session, medicine, req.patient_ref, on)
    testpoints.reached("dispense.after_window_read")

    candidate = engine.Candidate(
        medicine_code=req.medicine_code,
        patient_ref=req.patient_ref,
        quantity=req.quantity,
        dispensed_at=to_utc(req.dispensed_at),
        authorisation_ref=payload["authorisation_ref"],
    )
    facts = engine.MedicineFacts(medicine.id, medicine.code, medicine.is_active) if medicine else None
    verdict = engine.evaluate(
        candidate,
        facts,
        rules,
        history,
        now=clock.now(),
        future_tolerance=timedelta(seconds=get_settings().future_dispense_tolerance_seconds),
    )

    attempt = DispenseAttempt(
        idempotency_key=req.idempotency_key,
        request_fingerprint=fp,
        request_body=payload,
        patient_ref=req.patient_ref,
        medicine_code=req.medicine_code,
        created_at=clock.now(),
        created_by=actor,
    )

    if not verdict.accepted:
        attempt.outcome = "rejected"
        attempt.http_status = 422
        attempt.reason_codes = [v.code for v in verdict.violations]
        attempt.response_body = {}
        session.add(attempt)
        session.flush()  # assigns attempt.id, which the client gets back for support/audit
        attempt.response_body = problem_body(
            status=422,
            code=Codes.DISPENSE_REJECTED,
            title="Dispense rejected",
            detail=f"{len(verdict.violations)} rule(s) violated",
            instance=INSTANCE,
            errors=verdict.violations,
            extra={"attempt_id": attempt.id, "business_date": on.isoformat()},
        )
        session.commit()
        return DispenseResult(422, attempt.response_body, replayed=False)

    assert medicine is not None and verdict.governing_rule is not None
    dispense = Dispense(
        medicine_id=medicine.id,
        formulary_rule_id=verdict.governing_rule.id,
        patient_ref=req.patient_ref,
        quantity=req.quantity,
        dispensed_at=to_utc(req.dispensed_at),
        authorisation_ref=payload["authorisation_ref"],
        idempotency_key=req.idempotency_key,
        recorded_at=clock.now(),
        recorded_by=actor,
    )
    session.add(dispense)
    session.flush()
    body = jsonable(dispense_out(dispense, medicine))
    attempt.outcome = "accepted"
    attempt.http_status = 201
    attempt.reason_codes = []
    attempt.dispense_id = dispense.id
    attempt.response_body = body
    session.add(attempt)
    session.commit()
    return DispenseResult(201, body, replayed=False)


def window_total(session: Session, medicine_id: int, patient_ref: str, lo_day: Any, hi_day: Any) -> int:
    """Diagnostic helper used by tests and the seed verifier."""
    lo, hi = utc_bounds(lo_day, hi_day)
    return int(
        session.scalar(
            select(func.coalesce(func.sum(Dispense.quantity), 0)).where(
                Dispense.medicine_id == medicine_id,
                Dispense.patient_ref == patient_ref,
                Dispense.dispensed_at >= lo,
                Dispense.dispensed_at < hi,
            )
        )
        or 0
    )
