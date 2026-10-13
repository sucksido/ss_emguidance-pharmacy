"""indexes for the listing endpoints and partial-match medicine search

Each index exists for one access path (DECISIONS.md, ADR-005); before/after
plans and latencies are in docs/perf/.

* medicines: trigram GIN on name and code serves ILIKE '%term%' (a b-tree
  cannot serve a leading wildcard); b-tree (name, id) serves the ordered,
  keyset-paginated catalogue without a sort.
* dispenses: one b-tree per filter shape of GET /dispenses, each ending in
  (dispensed_at, id) so "newest first" + keyset is an index range scan that
  stops after limit+1 rows. (patient_ref, medicine_id, dispensed_at) from
  0002 already serves the two-filter case and the 30-day window read.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX ix_medicines_name_trgm ON medicines USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX ix_medicines_code_trgm ON medicines USING gin (code gin_trgm_ops)")
    op.create_index("ix_medicines_name_id", "medicines", ["name", "id"])

    op.create_index("ix_dispenses_time", "dispenses", ["dispensed_at", "id"])
    op.create_index("ix_dispenses_patient_time", "dispenses", ["patient_ref", "dispensed_at", "id"])
    op.create_index("ix_dispenses_medicine_time", "dispenses", ["medicine_id", "dispensed_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_dispenses_medicine_time", table_name="dispenses")
    op.drop_index("ix_dispenses_patient_time", table_name="dispenses")
    op.drop_index("ix_dispenses_time", table_name="dispenses")
    op.drop_index("ix_medicines_name_id", table_name="medicines")
    op.execute("DROP INDEX ix_medicines_code_trgm")
    op.execute("DROP INDEX ix_medicines_name_trgm")
    # No CASCADE: if anything else came to depend on pg_trgm this fails loudly
    # instead of silently dropping someone else's objects.
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
