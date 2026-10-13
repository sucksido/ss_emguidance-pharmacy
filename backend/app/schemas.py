from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
IdempotencyKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$")
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- medicines


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    effective_from: date
    effective_to: date | None = Field(description="Exclusive. null = open-ended.")
    max_quantity_per_dispense: int
    max_quantity_per_30_days: int
    requires_authorisation: bool
    superseded_by_id: int | None
    created_at: datetime
    created_by: str | None
    status: Literal["past", "in_force", "scheduled"]


class MedicineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    form: str
    strength_value: Decimal
    strength_unit: str
    is_active: bool


class MedicineDetailOut(MedicineOut):
    current_rule: RuleOut | None
    business_date: date = Field(description="Today's Africa/Johannesburg date used to pick current_rule.")


class RuleHistoryOut(BaseModel):
    medicine_code: str
    business_date: date
    in_force_rule_id: int | None
    items: list[RuleOut]


class NewRuleIn(StrictModel):
    effective_from: date
    effective_to: date | None = Field(
        default=None,
        description=(
            "Exclusive end date. Omit to take over the remainder of the superseded period "
            "(or run until the next scheduled rule, or indefinitely)."
        ),
    )
    max_quantity_per_dispense: int = Field(gt=0, strict=True)
    max_quantity_per_30_days: int = Field(gt=0, strict=True)
    requires_authorisation: bool

    # Field-level validators (not a model validator) so the error's ``loc`` - and
    # therefore the ``field`` in the error contract - names the offending field.
    @field_validator("effective_to")
    @classmethod
    def _period_order(cls, v: date | None, info: ValidationInfo) -> date | None:
        start = info.data.get("effective_from")
        if v is not None and start is not None and v <= start:
            raise PydanticCustomError("period_order", "effective_to must be after effective_from")
        return v

    @field_validator("max_quantity_per_30_days")
    @classmethod
    def _window_ge_dispense(cls, v: int, info: ValidationInfo) -> int:
        per = info.data.get("max_quantity_per_dispense")
        if per is not None and v < per:
            raise PydanticCustomError(
                "window_lt_dispense", "max_quantity_per_30_days must be >= max_quantity_per_dispense"
            )
        return v


class SupersedeOut(BaseModel):
    rule: RuleOut
    superseded_rule: RuleOut | None


# ---------------------------------------------------------------- dispenses


class DispenseIn(StrictModel):
    medicine_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    patient_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    quantity: int = Field(gt=0, strict=True)
    dispensed_at: AwareDatetime = Field(description="Must carry a UTC offset. May be in the past.")
    authorisation_ref: Annotated[str, StringConstraints(max_length=64)] | None = None
    idempotency_key: IdempotencyKey


class DispenseOut(BaseModel):
    id: int
    medicine_code: str
    medicine_name: str
    patient_ref: str
    quantity: int
    dispensed_at: datetime
    business_date: date
    authorisation_ref: str | None
    formulary_rule_id: int
    idempotency_key: str
    recorded_at: datetime


class AttemptOut(BaseModel):
    id: int
    idempotency_key: str
    outcome: str
    http_status: int
    reason_codes: list[str]
    patient_ref: str
    medicine_code: str
    dispense_id: int | None
    created_at: datetime
