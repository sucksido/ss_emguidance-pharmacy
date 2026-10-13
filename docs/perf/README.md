# Performance evidence

How to reproduce (stack running, after `docker compose exec api python -m app.seed [--scale N]`):

```bash
docker compose exec api python -m app.bench            # p50/p95/p99 per listing endpoint over HTTP; exits non-zero if any p95 >= 300 ms
docker compose exec api python -m app.bench --explain  # also prints EXPLAIN (ANALYZE, BUFFERS) for each listing query
```

| File | Dataset | Notes |
|---|---|---|
| `before-0004-scale10.txt` | 10x, migrations 0001-0003 only | baseline: seq scans, worst p95 62.8 ms |
| `after-0004-scale10.txt` | 10x, all migrations | worst p95 14.1 ms |
| `scale1.txt` | 1x (the brief's volume) | worst p95 14.5 ms |
| `scale100.txt` | 100x (500k dispenses, 50k medicines) | worst p95 22.1 ms |

Measured in the development container (PostgreSQL 16 local, uvicorn 2 workers), sequential requests, 200-300 per endpoint after 20 warm-up.
