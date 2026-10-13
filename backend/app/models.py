"""ORM mapping. The Alembic migrations are the source of truth for the schema;
these classes mirror them (constraints are declared here too so that the
intent is visible when reading the model, but nothing calls ``create_all``)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    form: Mapped[str] = mapped_column(String(40))
    strength_value: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    strength_unit: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rules: Mapped[list[FormularyRule]] = relationship(
        back_populates="medicine", order_by="FormularyRule.effective_from"
    )


class FormularyRule(Base):
    __tablename__ = "formulary_rules"
    __table_args__ = (
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_rule_period_positive"),
        CheckConstraint("max_quantity_per_dispense > 0", name="ck_rule_max_per_dispense_positive"),
        CheckConstraint(
            "max_quantity_per_30_days >= max_quantity_per_dispense", name="ck_rule_window_ge_per_dispense"
        ),
        # The no-overlap EXCLUDE constraint lives in migration 0001; SQLAlchemy has
        # no portable construct for it and it must not be "validated" here.
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="RESTRICT"))
    effective_from: Mapped[date] = mapped_column(Date)
    # Exclusive upper bound; NULL means open-ended.
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    max_quantity_per_dispense: Mapped[int] = mapped_column(Integer)
    max_quantity_per_30_days: Mapped[int] = mapped_column(Integer)
    requires_authorisation: Mapped[bool] = mapped_column(Boolean)
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("formulary_rules.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    medicine: Mapped[Medicine] = relationship(back_populates="rules")

    def covers(self, d: date) -> bool:
        return self.effective_from <= d and (self.effective_to is None or d < self.effective_to)


class Dispense(Base):
    __tablename__ = "dispenses"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_dispense_quantity_positive"),
        CheckConstraint("length(patient_ref) > 0", name="ck_dispense_patient_ref_nonempty"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="RESTRICT"))
    # The rule this dispense was validated against (pinned for audit; migration 0003).
    formulary_rule_id: Mapped[int] = mapped_column(ForeignKey("formulary_rules.id", ondelete="RESTRICT"))
    patient_ref: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    dispensed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    authorisation_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recorded_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    medicine: Mapped[Medicine] = relationship()


class DispenseAttempt(Base):
    """Every POST /dispenses that passed schema validation, accepted or rejected.

    Doubles as the idempotency store: the stored response is replayed verbatim.
    """

    __tablename__ = "dispense_attempts"
    __table_args__ = (
        CheckConstraint("outcome IN ('accepted', 'rejected')", name="ck_attempt_outcome"),
        CheckConstraint(
            "(outcome = 'accepted') = (dispense_id IS NOT NULL)", name="ck_attempt_accepted_has_dispense"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outcome: Mapped[str] = mapped_column(String(16))
    http_status: Mapped[int] = mapped_column(SmallInteger)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    dispense_id: Mapped[int | None] = mapped_column(ForeignKey("dispenses.id"), nullable=True, unique=True)
    patient_ref: Mapped[str] = mapped_column(String(64))
    medicine_code: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
