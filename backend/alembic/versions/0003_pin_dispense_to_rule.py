"""pin each dispense to the formulary rule it was validated against (data backfill)

Until this revision the governing rule of a dispense was only derivable by
re-running the "rule in force at dispensed_at" lookup. This migration
materialises that lookup into dispenses.formulary_rule_id for every existing
row, then makes the column mandatory.

The backfill evaluates the business date in Africa/Johannesburg - exactly the
same boundary the application uses (app/timeutil.py) - so a dispense at
2026-03-31T23:30:00Z (01:30 SAST on 1 April) is pinned to the April rule.

If any existing dispense has no rule in force at its business date the
migration aborts rather than inventing a link: that row is a data-quality
problem a human must look at.

Downgrade drops the column. Nothing is lost, because the value is derivable
from data that remains (and is re-derived on the next upgrade).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dispenses", sa.Column("formulary_rule_id", sa.BigInteger, nullable=True))

    op.execute(
        """
        UPDATE dispenses AS d
           SET formulary_rule_id = r.id
          FROM formulary_rules AS r
         WHERE r.medicine_id = d.medicine_id
           AND daterange(r.effective_from, r.effective_to, '[)')
               @> (d.dispensed_at AT TIME ZONE 'Africa/Johannesburg')::date
        """
    )

    op.execute(
        """
        DO $$
        DECLARE orphans bigint;
        BEGIN
            SELECT count(*) INTO orphans FROM dispenses WHERE formulary_rule_id IS NULL;
            IF orphans > 0 THEN
                RAISE EXCEPTION
                    'migration 0003: % dispense(s) have no formulary rule in force at their business date',
                    orphans;
            END IF;
        END $$;
        """
    )

    op.alter_column("dispenses", "formulary_rule_id", nullable=False)
    op.create_foreign_key(
        "fk_dispense_rule", "dispenses", "formulary_rules", ["formulary_rule_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_dispenses_rule", "dispenses", ["formulary_rule_id"])


def downgrade() -> None:
    op.drop_index("ix_dispenses_rule", table_name="dispenses")
    op.drop_constraint("fk_dispense_rule", "dispenses", type_="foreignkey")
    op.drop_column("dispenses", "formulary_rule_id")
