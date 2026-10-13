"""dispenses and the dispense attempt log (also the idempotency store)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dispenses",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "medicine_id",
            sa.BigInteger,
            sa.ForeignKey("medicines.id", ondelete="RESTRICT", name="fk_dispense_medicine"),
            nullable=False,
        ),
        sa.Column("patient_ref", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("dispensed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorisation_ref", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("recorded_by", sa.String(100), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_dispenses_idempotency_key"),
        sa.CheckConstraint("quantity > 0", name="ck_dispense_quantity_positive"),
        sa.CheckConstraint("length(patient_ref) > 0", name="ck_dispense_patient_ref_nonempty"),
    )
    # Serves both the rolling-window sum (equality on the first two columns,
    # range on the third) and the ledger filtered by patient + medicine.
    op.create_index(
        "ix_dispenses_patient_medicine_time", "dispenses", ["patient_ref", "medicine_id", "dispensed_at"]
    )

    op.create_table(
        "dispense_attempts",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("request_body", JSONB, nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("http_status", sa.SmallInteger, nullable=False),
        sa.Column("response_body", JSONB, nullable=False),
        sa.Column("reason_codes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "dispense_id",
            sa.BigInteger,
            sa.ForeignKey("dispenses.id", name="fk_attempt_dispense"),
            nullable=True,
        ),
        sa.Column("patient_ref", sa.String(64), nullable=False),
        sa.Column("medicine_code", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_attempts_idempotency_key"),
        sa.UniqueConstraint("dispense_id", name="uq_attempts_dispense"),
        sa.CheckConstraint("outcome IN ('accepted', 'rejected')", name="ck_attempt_outcome"),
        # An accepted attempt always points at its dispense; a rejected one never does.
        sa.CheckConstraint(
            "(outcome = 'accepted') = (dispense_id IS NOT NULL)", name="ck_attempt_accepted_has_dispense"
        ),
    )
    op.create_index("ix_attempts_patient_created", "dispense_attempts", ["patient_ref", "created_at"])


def downgrade() -> None:
    op.drop_table("dispense_attempts")
    op.drop_table("dispenses")
