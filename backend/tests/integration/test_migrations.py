"""Every migration downgrades cleanly, and 0003's data backfill is correct."""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app import db as app_db
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.no_db_cleanup


@pytest.fixture(autouse=True)
def back_to_head():
    app_db.reset_engine()
    yield
    app_db.reset_engine()
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def _tables():
    return set(inspect(app_db.get_engine()).get_table_names()) - {"alembic_version"}


def test_each_revision_downgrades_and_reupgrades_cleanly():
    cfg = alembic_config()
    revisions = [s.revision for s in ScriptDirectory.from_config(cfg).walk_revisions("base", "heads")][::-1]
    command.downgrade(cfg, "base")
    app_db.reset_engine()
    assert _tables() == set()
    for rev in revisions:
        command.upgrade(cfg, rev)
        command.downgrade(cfg, "-1")
        command.upgrade(cfg, rev)
    app_db.reset_engine()
    assert {"medicines", "formulary_rules", "dispenses", "dispense_attempts"} <= _tables()
    command.downgrade(cfg, "base")
    app_db.reset_engine()
    assert _tables() == set()


def _seed_at_0002(conn):
    conn.execute(
        text(
            "INSERT INTO medicines (id, code, name, form, strength_value, strength_unit) "
            "OVERRIDING SYSTEM VALUE VALUES (1, 'M1', 'M1', 'tablet', 1, 'mg')"
        )
    )
    conn.execute(
        text(
            "INSERT INTO formulary_rules (id, medicine_id, effective_from, effective_to, max_quantity_per_dispense,"
            " max_quantity_per_30_days, requires_authorisation) OVERRIDING SYSTEM VALUE VALUES"
            " (10, 1, '2026-01-01', '2026-04-01', 5, 10, false),"
            " (11, 1, '2026-04-01', NULL, 5, 10, false)"
        )
    )


def _dispense(conn, did, at):
    conn.execute(
        text(
            "INSERT INTO dispenses (id, medicine_id, patient_ref, quantity, dispensed_at, idempotency_key)"
            " OVERRIDING SYSTEM VALUE VALUES (:id, 1, 'P', 1, :at, :k)"
        ),
        {"id": did, "at": at, "k": f"k{did}"},
    )


def test_0003_backfills_rule_link_using_johannesburg_business_date():
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0002")
    with app_db.get_engine().begin() as conn:
        _seed_at_0002(conn)
        _dispense(conn, 1, "2026-03-31T21:59:59Z")  # 23:59:59 SAST 31 Mar -> rule 10
        _dispense(conn, 2, "2026-03-31T22:00:00Z")  # 00:00:00 SAST  1 Apr -> rule 11 (UTC date says March!)
        _dispense(conn, 3, "2026-02-10T08:00:00Z")  # -> rule 10
    app_db.reset_engine()

    command.upgrade(cfg, "0003")
    with app_db.get_engine().connect() as conn:
        links = dict(conn.execute(text("SELECT id, formulary_rule_id FROM dispenses ORDER BY id")).all())
        nullable = conn.scalar(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'dispenses' AND column_name = 'formulary_rule_id'"
            )
        )
    assert links == {1: 10, 2: 11, 3: 10}
    assert nullable == "NO"

    app_db.reset_engine()
    command.downgrade(cfg, "0002")
    with app_db.get_engine().connect() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("dispenses")}
        assert "formulary_rule_id" not in cols
        assert conn.scalar(text("SELECT count(*) FROM dispenses")) == 3  # data survives the downgrade


def test_0003_refuses_to_invent_links_for_orphaned_dispenses():
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0002")
    with app_db.get_engine().begin() as conn:
        _seed_at_0002(conn)
        _dispense(conn, 1, "2025-06-01T10:00:00Z")  # before any rule
    app_db.reset_engine()
    with pytest.raises(Exception, match="no formulary rule in force"):
        command.upgrade(cfg, "0003")
    app_db.reset_engine()
    with app_db.get_engine().connect() as conn:
        # transaction_per_migration: the failed revision rolled back completely.
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
