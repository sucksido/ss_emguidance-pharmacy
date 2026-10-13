"""Integration tests run against a real PostgreSQL database (``<db>_test``),
migrated with the real Alembic migrations. Exclusion constraints, advisory
locks and row locks are the subject under test, so there is no SQLite or mock
substitute here."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def _test_url() -> str:
    explicit = os.environ.get("APP_TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("APP_DATABASE_URL", "postgresql+psycopg://pharmacy:pharmacy@localhost:5432/pharmacy")
    url = make_url(base)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


TEST_URL = _test_url()
# Point the application at the test database before anything imports settings.
os.environ["APP_DATABASE_URL"] = TEST_URL

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as app_db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import FormularyRule, Medicine  # noqa: E402
from app.timeutil import FixedClock  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NOW = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)  # 12:00 SAST, Tuesday 30 June 2026


def _ensure_database() -> None:
    url = make_url(TEST_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": url.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


def alembic_config() -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["database_url"] = TEST_URL
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    _ensure_database()
    get_settings.cache_clear()
    app_db.reset_engine()
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    app_db.reset_engine()


def truncate_all() -> None:
    with app_db.get_engine().begin() as conn:
        conn.execute(
            text("TRUNCATE dispense_attempts, dispenses, formulary_rules, medicines RESTART IDENTITY CASCADE")
        )


@pytest.fixture(autouse=True)
def clean_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    if "no_db_cleanup" in request.keywords:
        yield
        return
    truncate_all()
    yield


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def client(clock: FixedClock) -> Iterator[TestClient]:
    app.state.clock = clock
    with TestClient(app) as c:
        yield c
    app.state.clock = None


@pytest.fixture
def session():
    s = app_db.session_factory()()
    yield s
    s.close()


class Factory:
    """Builds reference data directly in the DB (there is no medicine-create endpoint)."""

    def medicine(self, code: str = "PARA500", *, active: bool = True, name: str | None = None) -> Medicine:
        with app_db.session_factory()() as s:
            m = Medicine(
                code=code,
                name=name or f"Medicine {code}",
                form="tablet",
                strength_value=Decimal("500"),
                strength_unit="mg",
                is_active=active,
            )
            s.add(m)
            s.commit()
            return m

    def rule(
        self,
        medicine: Medicine,
        frm: date,
        to: date | None = None,
        *,
        per: int = 10,
        window: int = 30,
        auth: bool = False,
    ) -> FormularyRule:
        with app_db.session_factory()() as s:
            r = FormularyRule(
                medicine_id=medicine.id,
                effective_from=frm,
                effective_to=to,
                max_quantity_per_dispense=per,
                max_quantity_per_30_days=window,
                requires_authorisation=auth,
            )
            s.add(r)
            s.commit()
            return r


@pytest.fixture
def factory() -> Factory:
    return Factory()


def dispense_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "medicine_code": "PARA500",
        "patient_ref": "PT-0001",
        "quantity": 5,
        "dispensed_at": "2026-06-15T09:00:00+02:00",
        "idempotency_key": f"k-{uuid.uuid4()}",
    }
    body.update(overrides)
    return body
