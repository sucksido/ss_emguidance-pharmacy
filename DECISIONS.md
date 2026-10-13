# Decisions

Each entry gives what I chose, what I considered instead, and what I gave up. Where the brief was ambiguous, I made a call and recorded it under **Assumptions** at the end.

---

## ADR-001 — Rule versioning: effective-dated rows, truncate-on-supersede, history is append-only

**Context.** Rules change over time. A dispense must be judged by the rule in force at its `dispensed_at`. "Introduce a rule from a date, superseding what is in force" has to say what happens to the old rule and to a start date that falls inside an existing period.

**Decision.**
- One row per rule period: `effective_from` (inclusive) and `effective_to` (exclusive, `NULL` = open-ended). Both are **local dates in Africa/Johannesburg**, so a rule changes at local midnight, not UTC midnight.
- No overlap is enforced by `EXCLUDE USING gist (medicine_id WITH =, daterange(effective_from, effective_to, '[)') WITH &&)`. Half-open ranges make adjacent periods (`…→1 Jun`, `1 Jun→…`) legal and touching-but-overlapping ones illegal. Nothing else is needed.
- **Supersede at date D** (under `SELECT … FOR UPDATE` on the medicine):
  - The rule C covering D is *truncated* to end at D and gets `superseded_by_id`. Its limits are never edited.
  - The new rule's end defaults to C's original end, so a supersede never opens a gap. An explicit earlier end would leave a gap, so it is refused (422 `SUPERSEDE_LEAVES_GAP`). If no rule covers D, the end defaults to the next scheduled rule's start (filling the gap), or open-ended.
  - A new period that would run into a later scheduled rule is refused (409 `RULE_OVERLAPS_LATER_RULE`). I chose not to silently delete or shorten future rules.
  - If C *starts* on D, the request is refused (409 `RULE_ALREADY_STARTS_ON_DATE`). Replacing it would delete history.
  - **A change may not alter which rule governs an existing dispense** (409 `RETROACTIVE_RULE_CHANGE`). Backdated rules are allowed only where no dispense has been recorded in the affected range. This keeps "a dispense in March is governed by March's rules" true after the fact, not just at write time.
- Each dispense stores `formulary_rule_id` (migration 0003), so the audit question "which rule allowed this?" is a join, not a recomputation.

**Considered.**
- *Fully bitemporal rules* (valid time + transaction time, never update a row). This is the most auditable option and lets you answer "what did we believe the rules were on 3 March?". I rejected it for this scope: every read needs `AND recorded_at <= …`, the exclusion constraint has to range over two dimensions, and because retroactive changes are refused, the only mutation left is the truncation, which `superseded_by_id` + `created_at` already explain.
- *Splitting C around a bounded new rule* (temporary override that then reverts). This is useful, but it creates a third row that copies C's limits, which blurs "rules are authored, not derived". If it is ever needed, it can be added as an explicit operation.
- *Validating overlap in Python only.* The brief rules this out, and it is unsafe under concurrency: see `test_concurrent_overlapping_inserts_cannot_both_commit`.

**Gave up.** We cannot correct a rule after dispenses have been made under it. That needs a deliberate "amend with re-evaluation" workflow I did not build. A truncated row does not keep its own original `effective_to`. You recover it by following `superseded_by_id` to the successor, which inherits that end by default. At 10× I would add an append-only `formulary_rule_events` table rather than make the main table bitemporal.

---

## ADR-002 — Concurrency for the rolling 30-day limit: per-(medicine, patient) advisory lock

**Context.** Rule 9: two simultaneous dispenses for one patient and medicine must not jointly exceed `max_quantity_per_30_days`. This is a classic write skew. Both transactions read a total of 0, both insert, and no row-level conflict ever happens, because they insert *different* rows.

**Decision.** Inside the dispense transaction, call `pg_advisory_xact_lock(hashtextextended('dispense-window:<medicine_id>:<patient_ref>', 0))` before reading the window. It is released automatically at commit or rollback. The full lock order is idempotency key → medicine row `FOR SHARE` → (medicine, patient). The supersede path takes only the medicine row `FOR UPDATE`, so there is no cycle and no deadlock.

**How it is proven** (`tests/integration/test_concurrency.py`). Two threads, each with its own connection. A test hook pauses the first transaction *after* it has read the window and *before* it inserts. The test then polls `pg_locks` until it sees the second transaction **waiting** on the advisory lock, and only then releases the first. The test fails if that wait is never observed, so it cannot pass by accident of scheduling. `test_supersede_cannot_slip_under_an_in_flight_dispense` does the same for the medicine-row `FOR SHARE`: a concurrent supersede is observed waiting, then refuses because it now sees the dispense. A **negative control** removes only the advisory lock and asserts that the same choreography *does* breach the limit (12 > 10). I also mutation-tested it: with the lock body replaced by `return None`, the main test and the 20-thread stress test both fail.

**Considered.**
- *SERIALIZABLE isolation.* It is correct and needs no hand-written lock, but it aborts with serialization failures that every caller must retry. It can also raise false-positive serialization failures at higher load, because predicate locks are coarse-grained, and the retry logic would have to replay the attempt-log write carefully. I preferred blocking to aborting for a short critical section.
- *A lock row per (patient, medicine)* (`INSERT … ON CONFLICT DO NOTHING; SELECT … FOR UPDATE`). It is equivalent, visible in normal tooling and works across connection poolers in transaction mode. The cost is a table that grows with every pair ever seen, plus an extra write per dispense.
- *Locking the medicine row `FOR UPDATE`.* Simple, but it serialises every dispense of a medicine across all patients. `test_different_patients_are_not_serialised_against_each_other` guards against regressing to that.

**Gave up / costs.**
- Requests for the *same* patient and medicine queue behind each other for the length of one short transaction. That is fine at pharmacy-counter rates.
- 64-bit hash collisions could rarely make two unrelated pairs wait on each other. That affects throughput, not correctness.
- Advisory locks only protect writers that take them. A script that inserts dispenses directly bypasses the check. The seed does this, but validates with the same engine and re-checks every window in SQL afterwards.
- At 10× and beyond with PgBouncer in transaction mode, transaction-scoped advisory locks still work (session-scoped ones would not).

---

## ADR-003 — Pagination: keyset (cursor), opaque, bound to its filters

**Decision.** All listings return `{ items, page: { limit, has_more, next_cursor } }`. The cursor is base64url JSON of the last row's sort key plus a 12-character hash of the filters. Medicines sort by `(name, id)`; dispenses by `(dispensed_at DESC, id DESC)`. The query is `WHERE (sort_key) < (:cursor)` plus `LIMIT n+1`, served directly by a matching b-tree. A cursor reused with different filters is a 422 `INVALID_CURSOR`, not a silently wrong page. Limit is capped at 100. Rule history is not paginated: it is bounded (3–5 rows per medicine) and the UI needs all of it to draw the timeline.

**Considered.** *Offset/limit with total count.* It allows page numbers and "jump to page 40", but the cost grows with the offset. `COUNT(*)` on a filtered dispense table is a full index scan at scale, and pages shift when a backdated dispense is inserted while someone is paging. Newest-first ledgers with backdated inserts are exactly where offset drifts.

**Gave up.** There are no total counts and no random page access. "Previous" is done client-side by keeping a stack of cursors (`CursorPager`). Ordering is by `dispensed_at` (when it happened), not `recorded_at`. That is right for a patient ledger, but a backdated dispense can appear on a page the user has already passed. The alternative, ordering by `recorded_at`, would show the ledger in an order a pharmacist would find wrong.

---

## ADR-004 — Error contract: RFC 9457 problem+json with `code` and a full `errors[]` list

**Decision.** Every non-2xx response, whether business rejection, schema validation, 404, 409 or 500, is `application/problem+json`:

```json
{ "type": "https://pharmacy.example/problems/dispense-rejected", "title": "Dispense rejected", "status": 422,
  "code": "DISPENSE_REJECTED", "detail": "3 rule(s) violated", "instance": "/api/v1/dispenses",
  "attempt_id": 41, "business_date": "2026-10-13",
  "errors": [ { "code": "MAX_QUANTITY_PER_DISPENSE_EXCEEDED", "field": "quantity", "rule_id": 211,
                "message": "Quantity 60 exceeds the maximum of 28 per dispense.", "meta": { "limit": 28, "requested": 60 } } ] }
```

- `code` (top level) is what the client switches on. `errors[].code` is a stable reason. `errors[].field` is the **request body field name**, or `null` when the reason belongs to the form as a whole. `rule_id` points at the formulary rule that produced it. `meta` holds the numbers, so a UI never parses `message`.
- Unhandled exceptions become a 500 problem document in the request middleware (not a Starlette exception handler, which would run outside it), so even crashes carry `X-Request-ID` and CORS headers and never leak internals. Out-of-range dates (outside 1900–2100), NUL characters and forged cursors are rejected as 422 field errors before they can reach date arithmetic or SQL (`tests/integration/test_edge_inputs.py`).
- Pydantic validation errors go through the same envelope (`VALIDATION_FAILED`, `FIELD_REQUIRED` / `FIELD_INVALID`). Cross-field checks are written as *field* validators so they land on a field.
- Status codes: 422 for a well-formed request the business rules reject; 409 for a conflict with existing state (rule history); 404 for a missing path resource. An unknown `medicine_code` *inside a dispense body* is a 422 field error, not a 404, because it is a fact about the request, not the URL.

**Considered.** FastAPI's default `{"detail": …}`, which has a different shape for validation and HTTP errors and no field mapping for business errors. A bespoke envelope, which would have been equally expressive but less recognisable than a published standard.

**Gave up.** The bodies are slightly verbose. The `type` URIs are not dereferenceable documentation pages.

---

## ADR-005 — Indexing: one index per access path, validated with EXPLAIN and a latency benchmark

| Access path | Index |
|---|---|
| Rule in force on date D / no-overlap | GiST exclusion `(medicine_id, daterange)` (0001) |
| 30-day window read; ledger filtered by patient + medicine | `(patient_ref, medicine_id, dispensed_at)` (0002) |
| `GET /dispenses` unfiltered, newest first | `(dispensed_at, id)` (0004) |
| `GET /dispenses?patient_ref=` | `(patient_ref, dispensed_at, id)` (0004) |
| `GET /dispenses?medicine_code=` | `(medicine_id, dispensed_at, id)` (0004) |
| Medicine search `ILIKE '%term%'` | `pg_trgm` GIN on `name` and on `code` (0004) |
| Catalogue first page, keyset | `(name, id)` (0004) |

**Validation.** `python -m app.bench` (how to run: `docs/perf/README.md`) makes full HTTP round trips (200 per endpoint after warm-up, random parameters drawn from the data) and prints p50/p95/p99. `--explain` prints `EXPLAIN (ANALYZE, BUFFERS)`. Results are in `docs/perf/`. I captured a baseline at 10× scale *before* migration 0004, because at 1× every table fits in a few pages and the planner rightly seq-scans, which would prove nothing:

| | before 0004 (10×) | after 0004 (10×) | after, 1× (brief) | after, 100× (500k dispenses) |
|---|---|---|---|---|
| worst p95 | 62.8 ms (`/dispenses` unfiltered: seq scan + top-N sort) | 14.1 ms | 14.5 ms | 22.1 ms |

These were measured on the development container with a local PostgreSQL 16, not on a laptop through Docker Desktop. Rerun the command on the target machine. The plans show the change from `Seq Scan` to `Index Scan Backward using ix_dispenses_time` with `LIMIT 21`.

**Considered.** A single composite index for all dispense filters (it cannot serve `patient_ref` + order by `dispensed_at` without `medicine_id`). Full-text search for medicines (it is word-based, and a partial code like `00012` is not a word).

**Gave up.** Four b-trees on `dispenses` means four index writes per insert. That is cheap at counter rates and a deliberate read-over-write trade. Trigram indexes do not help with 1–2 character queries; those fall back to walking `(name, id)` with a filter, which is still fast because the page stops at 21 matches. Also noted from the plans: with both indexes present the planner sometimes serves the window read from `(medicine_id, dispensed_at, id)` instead of the patient-leading index. It is correct and fast here. At 10× I would watch it, and drop the 0002 index if it stays unused.

---

## ADR-006 — Time: UTC storage, Africa/Johannesburg business dates, one conversion module

**Decision.** All instants are `timestamptz`. Input must carry an offset; naive datetimes are rejected with a 422. All business logic works on **local calendar dates**: rule periods, "rule in force on" and the rolling window. `app/timeutil.py` is the only place that converts. Queries filter `dispensed_at` with UTC bounds of local midnights (`[start_of_day_utc(D-29), start_of_day_utc(D+1))`) rather than `(dispensed_at AT TIME ZONE …)::date`, so the b-tree on `dispensed_at` stays usable. Migration 0003 uses the same definition in SQL. The frontend captures wall-clock time *in Johannesburg* regardless of the browser's zone, and sends an explicit offset computed from the IANA zone database, not hard-coded.

**Considered.** Storing a local `dispensed_on` date column. It is faster to group by, but it duplicates the source of truth, and the conversion is cheap and not on a hot path.

**Gave up.** South Africa has no DST today, so the "23-hour day" edge cases are untested against a real DST transition. The code path would handle them, because it converts through `zoneinfo`.

---

## ADR-007 — Idempotency: the attempt log is the idempotency store; a reused key with a different payload is 422

**Decision.** `idempotency_key` is unique in `dispense_attempts`, which stores a SHA-256 fingerprint of the *canonical* request (timestamp normalised to UTC, authorisation trimmed) and the exact response body and status. A repeat with the same fingerprint replays that response, rejection or success, with `Idempotent-Replayed: true` and creates nothing. The same instant written with a different UTC offset counts as the same payload. Concurrent duplicates are serialised by an advisory lock on the key, and the unique constraint is the backstop (8 simultaneous duplicates produce 1 dispense and 7 replays).

**Different payload → 422 `IDEMPOTENCY_KEY_REUSED`** (field `idempotency_key`). This follows the IETF HTTPAPI *Idempotency-Key* draft, which uses 422 for key reuse with a different payload and reserves 409 for a request still in flight with the same key. That second case cannot surface here because concurrent duplicates wait on the lock. It is a client bug, not a transient state, so it must not be retryable. It is not logged as an attempt, because the key already belongs to another attempt.

**Considered.** 409 Conflict, which is defensible since "conflicts with the stored state of the key", but it would collide with the draft's meaning and with our 409s for rule history. Key in a header (`Idempotency-Key`), which is common, but the brief models it as a field of the dispense.

**Gave up.** Keys never expire (they are audit records). At 10× I would add a retention window for the replay index and keep the attempts in cold storage.

---

## ADR-008 — The rolling window and backdated dispenses

**Decision.** The window for a dispense on local date D is the 30 local calendar days D-29 … D, inclusive, regardless of the time of day. For a **backdated** dispense the engine checks two things:

1. its own window, which includes any dispense recorded earlier that occurred within it;
2. every *existing later* dispense on dates D+1 … D+29. Adding this one must not push *their* windows over *their* limit, judged by the rule in force on *their* date (`MAX_QUANTITY_PER_30_DAYS_EXCEEDED_LATER`, listing every affected date).

Without (2), the invariant "no dispense's window exceeds its limit" can be broken by inserting into the past. That is the bug the brief's sentence about backdating is pointing at.

**Considered.** An instant-based window `(t − 30×24h, t]`. It is simpler to state, but two dispenses on the same afternoon would see different totals depending on minutes. A business-day window also matches "evaluated in Africa/Johannesburg".

**Gave up.** The facts query reads up to 59 days of one patient's history for one medicine. That is trivial, and indexed.

---

## ADR-009 — Smaller calls

- **Sync SQLAlchemy + threadpool, not async.** The workload is DB-bound with short transactions. Sync code is easier to reason about around locks and gives cleaner stack traces. uvicorn runs 2 workers × FastAPI's 40-thread pool, with a SQLAlchemy pool of 10+20.
- **Schema-invalid requests are not written to the attempt log.** Rule 7 is about *rejected attempts*; a body that cannot be parsed has no reliable idempotency key or patient to file it under. They get the same problem+json response and the request ID in `X-Request-ID`.
- **Future-dated dispenses are rejected** (`DISPENSED_AT_IN_FUTURE`, 5-minute clock-skew tolerance). The brief allows backdating; a dispense "in the future" is a data-entry error.
- **Inactive is a current state, not versioned.** `is_active=false` blocks all new dispenses, including backdated ones. Versioning activation would be a separate effective-dated table.
- **Stub identity.** The `X-Actor` header is recorded on rules and attempts for audit. Authentication is out of scope.
- **Frontend scope.** All four views are built, plus the supersede form on the detail page. Not built: medicine create/edit (no API for it), an attempt-log view (the API exists: `GET /api/v1/dispense-attempts`), and e2e tests in CI (the screenshots in `docs/screenshots` come from a scripted Playwright run).

---

## Assumptions (ambiguities resolved)

1. `effective_to` is **exclusive**. The UI shows "last day" = `effective_to − 1`.
2. A rule's dates are Africa/Johannesburg calendar dates.
3. "30 days ending at `dispensed_at` (inclusive)" = 30 local calendar days including the dispense day.
4. `max_quantity_per_30_days ≥ max_quantity_per_dispense` is enforced (otherwise the per-dispense limit could never be reached).
5. An unknown medicine code in a dispense body is a *rejected attempt* (logged), not a 404.
6. Rejections are replayed for their idempotency key even if the rules would now accept the request. The key's outcome is fixed.
7. "Newest first" for dispenses means by `dispensed_at`, tie-broken by `id`.
