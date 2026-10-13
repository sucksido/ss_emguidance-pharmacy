# Pharmacy formulary & dispensing

Requires Docker with Compose v2. Ports used on the host: 8080 (web), 8000 (API), 5433 (PostgreSQL).

## Run

```bash
docker compose up --build
```

Migrations apply automatically when the API starts.

| What | URL |
|---|---|
| Web app | http://localhost:8080 |
| API (OpenAPI UI) | http://localhost:8000/api/v1/docs |

## Seed

```bash
docker compose exec api python -m app.seed
```

Replaces all data with 500 medicines, 3–5 rule periods each, 5,000 dispenses across 2,150 patient references over the last two years. Safe to re-run. `--scale 10` loads ten times as much.

## Test

Backend (unit + integration against a real PostgreSQL test database, created automatically):

```bash
docker compose exec api pytest
```

Frontend (Vitest):

```bash
docker compose run --rm frontend-tests
```

## Measure listing latency

After seeding, with the stack running:

```bash
docker compose exec api python -m app.bench            # p50/p95/p99 per listing endpoint; exits non-zero if any p95 >= 300 ms
docker compose exec api python -m app.bench --explain  # also prints EXPLAIN (ANALYZE, BUFFERS) for each listing query
```
