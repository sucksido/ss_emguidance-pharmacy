# Architecture

```
 Browser ──► web (nginx) ──/api/──► api (FastAPI, uvicorn ×2) ──► db (PostgreSQL 16)
             Angular SPA                 │
                                         ├─ app/api/         HTTP: routing, request parsing, status codes
                                         ├─ app/services/    transactions, locks, persistence
                                         ├─ app/domain/      rules_engine.py — pure decision logic, no I/O
                                         ├─ app/timeutil.py  the only UTC ⇄ Africa/Johannesburg boundary
                                         └─ app/errors.py    the problem+json error contract
```

**Request path for `POST /api/v1/dispenses`** (`app/services/dispensing.py`), one transaction:

1. `pg_advisory_xact_lock` on the idempotency key → if the key exists, replay the stored response (or 422 if the payload differs).
2. `SELECT … FOR SHARE` on the medicine row, so a rule supersede or deactivation cannot interleave.
3. `pg_advisory_xact_lock` on *(medicine, patient_ref)*, so the rolling-window read and the insert happen as one unit for that pair.
4. Load the facts: rules overlapping the dispense's business date + 29 days; this patient's dispenses of this medicine from 29 days before to 29 days after.
5. **`rules_engine.evaluate()` decides.** It returns every violation, each with the field and rule it relates to.
6. Write *either* the dispense plus an `accepted` attempt, *or* a `rejected` attempt only, then commit. Rule 7's two halves hold together because both rows share one commit.

**Where rule evaluation lives:** only in `app/domain/rules_engine.py`. It is a pure function from facts to a verdict, which is why it can be tested without a database (`tests/unit/test_rules_engine.py`), and why the seed script uses the same engine to generate valid data. The service layer gathers facts under the right locks. It never decides anything itself.

**Rule versioning** (`app/services/formulary.py`): rules are rows with a half-open local-date period `[effective_from, effective_to)`. A GiST exclusion constraint (`medicine_id WITH =, daterange(...) WITH &&`) makes overlapping periods impossible, whether the write comes from the application, a script or psql. A supersede truncates the rule in force and inserts the new one under a `FOR UPDATE` lock on the medicine. Each dispense stores the `formulary_rule_id` it was judged against.

**Time:** every timestamp is `timestamptz` (UTC). Every business concept (rule periods, the 30-day window) is a local calendar date in Africa/Johannesburg. `app/timeutil.py` is the only place that converts. Window queries filter on UTC bounds of local midnights, which keeps the `dispensed_at` b-tree usable.

**Read side** (`app/services/catalog.py`): keyset pagination with opaque cursors that are bound to their filters. Each listing has one index that matches its filter + sort (migration 0004, `docs/perf/`).

**Frontend** (`frontend/src/app`): standalone, zoneless Angular 21 with signals. `core/` holds the API client, the problem-to-form-error mapper, a generic `CursorPager` (switchMap cancellation, cursor stack for "previous") and Johannesburg wall-clock helpers. The four views live in `pages/` and are lazy-loaded. The URL is the state for search and the ledger.

**Schema** (Alembic, `backend/alembic/versions`): `0001` medicines + rules + exclusion constraint · `0002` dispenses + attempt log · `0003` adds `dispenses.formulary_rule_id` and backfills it (the data migration) · `0004` listing/search indexes.
