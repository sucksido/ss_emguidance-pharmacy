# AI usage

## Tools

- **Claude (Anthropic), in Claude Cowork's agent mode.** It was the primary implementation tool for the whole submission. Working from the brief and my direction, it wrote the code, migrations, tests, seed and benchmark scripts, Docker files and first drafts of these documents. It also ran everything against a real PostgreSQL 16, Python 3.12 and Node 22 toolchain while working, so it could see failures and correct them.
- Angular CLI (`ng new`) generated the frontend scaffold. Library versions are pinned to what the tests were run with.

## What it produced

Most of the code in this repository. Commits are incremental and in the order the work was done. Each one carries a `Co-Authored-By: Claude` trailer.

## Where output was changed or rejected

These happened during the build and are visible in the history:

| What the AI first produced | What happened | Why |
|---|---|---|
| `ErrorItem` dataclass with a field named `field` and `dataclasses.field(...)` imported as `field` | Import failed at collection time; fixed by importing `dataclasses` as a module | The class attribute shadowed the helper inside the class body |
| Unit tests for the rule-boundary cases | Two expectations were wrong (the test rules' 30-day limit was lower than the quantity), so they failed against correct engine code; the **tests** were fixed, not the engine | The engine was right to report both violations; it reports every violation |
| A cross-field check on new rules as a Pydantic *model* validator | Replaced by *field* validators | A model validator's error has no field `loc`, which would break the error contract's field mapping |
| A seed self-check query using a correlated subquery over a CTE | Ran for minutes at 10× scale; replaced by a `RANGE BETWEEN '29 days' PRECEDING` window function | O(n²). The replacement was then checked by deliberately corrupting three rows and confirming it reports 3 breaches |
| Angular 22 | Rejected in favour of Angular 21 | Angular 22 requires Node ≥ 22.22.3; 21 supports the Node 22 LTS in the Docker image |
| `npm install` | Failed with an npm arborist peer-resolution bug (`edgesOut`); `.npmrc` sets `legacy-peer-deps` | Toolchain bug, not a dependency conflict; `npm ci` from the lockfile is clean |
| DB fixtures in the root `tests/conftest.py` | Moved to `tests/integration/conftest.py` | Unit tests were needlessly requiring a database |
| Leftover "pre-truncation" variable and a dead loop in the seed | Removed | Code that has no purpose shouldn't ship |

## How correctness was checked rather than assumed

- The concurrency test was **mutation-tested**: with the advisory lock replaced by `return None` it fails (and so does the 20-thread stress test). It also refuses to pass unless `pg_locks` shows the second request actually waiting.
- The seed runs every generated dispense through the real rule engine, then an independent SQL query re-checks every 30-day window (0 breaches at 1×, 10× and 100×).
- The backend suite was run on a clean Python 3.12 virtualenv with the pinned requirements. The frontend was built from a clean `npm ci`.
- The four UI views were driven end-to-end with Playwright against the seeded API; screenshots are in `docs/screenshots/`.

## Not verified by the AI

Docker Hub was not reachable from the build environment, so `docker compose up` was **not** executed there. The compose file was validated with `docker compose config`, and every step the containers run (entrypoint migrations, seed, tests, production Angular build) was run natively. <!-- TODO(Success): after running `docker compose up --build` from a clean clone on your machine, replace this comment with a sentence saying so (and note anything you had to fix). -->

## My own review

<!-- TODO(Success): list what you changed or questioned yourself while reviewing (even small things). Only claim what you actually did. -->
