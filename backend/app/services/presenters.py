"""ORM row -> API representation. Kept apart so that the JSON stored in the
idempotency log and the JSON returned live are produced by the same code."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.models import Dispense, FormularyRule, Medicine
from app.schemas import DispenseOut, MedicineOut, RuleOut
from app.timeutil import business_date


def rule_status(rule: FormularyRule, today: date) -> str:
    if rule.effective_to is not None and rule.effective_to <= today:
        return "past"
    if rule.effective_from > today:
        return "scheduled"
    return "in_force"


def rule_out(rule: FormularyRule, today: date) -> RuleOut:
    return RuleOut(
        id=rule.id,
        effective_from=rule.effective_from,
        effective_to=rule.effective_to,
        max_quantity_per_dispense=rule.max_quantity_per_dispense,
        max_quantity_per_30_days=rule.max_quantity_per_30_days,
        requires_authorisation=rule.requires_authorisation,
        superseded_by_id=rule.superseded_by_id,
        created_at=rule.created_at,
        created_by=rule.created_by,
        status=rule_status(rule, today),  # type: ignore[arg-type]
    )


def medicine_out(m: Medicine) -> MedicineOut:
    return MedicineOut.model_validate(m)


def dispense_out(d: Dispense, medicine: Medicine) -> DispenseOut:
    return DispenseOut(
        id=d.id,
        medicine_code=medicine.code,
        medicine_name=medicine.name,
        patient_ref=d.patient_ref,
        quantity=d.quantity,
        dispensed_at=d.dispensed_at,
        business_date=business_date(d.dispensed_at),
        authorisation_ref=d.authorisation_ref,
        formulary_rule_id=d.formulary_rule_id,
        idempotency_key=d.idempotency_key,
        recorded_at=d.recorded_at,
    )


def jsonable(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")
