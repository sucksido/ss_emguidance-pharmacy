"""medicines and formulary rules, with database-enforced non-overlapping periods

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # btree_gist lets a GiST exclusion constraint combine "=" on a scalar column
    # with "&&" on a range.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "medicines",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("form", sa.String(40), nullable=False),
        sa.Column("strength_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("strength_unit", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_medicines_code"),
        sa.CheckConstraint("strength_value > 0", name="ck_medicine_strength_positive"),
    )

    op.create_table(
        "formulary_rules",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "medicine_id",
            sa.BigInteger,
            sa.ForeignKey("medicines.id", ondelete="RESTRICT", name="fk_rule_medicine"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("max_quantity_per_dispense", sa.Integer, nullable=False),
        sa.Column("max_quantity_per_30_days", sa.Integer, nullable=False),
        sa.Column("requires_authorisation", sa.Boolean, nullable=False),
        sa.Column(
            "superseded_by_id",
            sa.BigInteger,
            sa.ForeignKey("formulary_rules.id", name="fk_rule_superseded_by"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_rule_period_positive"),
        sa.CheckConstraint("max_quantity_per_dispense > 0", name="ck_rule_max_per_dispense_positive"),
        sa.CheckConstraint(
            "max_quantity_per_30_days >= max_quantity_per_dispense", name="ck_rule_window_ge_per_dispense"
        ),
    )

    # Business rule 8. Periods are half-open [effective_from, effective_to); a NULL
    # upper bound is +infinity. Because the check is performed by the index itself,
    # two concurrent transactions inserting overlapping periods cannot both commit:
    # the second blocks on the first's uncommitted index entry and then fails with
    # SQLSTATE 23P01 (exclusion_violation). The index also serves the
    # "rule in force on date D" lookup via the @> operator.
    op.execute(
        """
        ALTER TABLE formulary_rules
        ADD CONSTRAINT ex_rule_periods_no_overlap
        EXCLUDE USING gist (
            medicine_id WITH =,
            daterange(effective_from, effective_to, '[)') WITH &&
        )
        """
    )


def downgrade() -> None:
    op.drop_table("formulary_rules")
    op.drop_table("medicines")
    # No CASCADE: fails loudly rather than drop objects that are not ours.
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
