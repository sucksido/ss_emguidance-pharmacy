"""Latency benchmark for every listing endpoint, against a running API.

    python -m app.bench                       # 200 timed requests per endpoint, fails if any p95 >= 300 ms
    python -m app.bench --explain             # also print EXPLAIN (ANALYZE, BUFFERS) for the listing queries

Measures wall-clock time of a full HTTP round-trip (client -> uvicorn ->
FastAPI -> SQLAlchemy -> PostgreSQL -> JSON), sequentially, after a warm-up,
with parameters drawn at random from the seeded data so the cache is not
flattered by one hot key. Standard library only, so it runs in the API image.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
import urllib.parse
import urllib.request

from sqlalchemy import text

from app.db import get_engine

THRESHOLD_MS = 300.0


def _get(base: str, path: str, params: dict[str, object] | None = None) -> tuple[float, int]:
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    start = time.perf_counter()
    with urllib.request.urlopen(url, timeout=10) as res:
        res.read()
        status = res.status
    return (time.perf_counter() - start) * 1000, status


def _samples() -> dict[str, list]:
    with get_engine().connect() as conn:
        codes = [r[0] for r in conn.execute(text("SELECT code FROM medicines"))]
        names = [r[0] for r in conn.execute(text("SELECT name FROM medicines"))]
        patients = [r[0] for r in conn.execute(text("SELECT DISTINCT patient_ref FROM dispenses"))]
        pairs = [tuple(r) for r in conn.execute(text(
            "SELECT DISTINCT d.patient_ref, m.code FROM dispenses d JOIN medicines m ON m.id = d.medicine_id"
        ))]
    if not codes or not patients:
        sys.exit("No data. Run `python -m app.seed` first.")
    return {"codes": codes, "names": names, "patients": patients, "pairs": pairs}


def _scenarios(s: dict[str, list], rng: random.Random):
    def name_fragment() -> str:
        n = rng.choice(s["names"]).lower()
        i = rng.randrange(0, max(1, len(n) - 4))
        return n[i : i + rng.randint(3, 5)]

    return {
        "GET /medicines (no filter)": lambda: ("/api/v1/medicines", {}),
        "GET /medicines?q=<name fragment>": lambda: ("/api/v1/medicines", {"q": name_fragment()}),
        "GET /medicines?q=<code fragment>": lambda: ("/api/v1/medicines", {"q": rng.choice(s["codes"])[3:8]}),
        "GET /medicines/{code}": lambda: (f"/api/v1/medicines/{rng.choice(s['codes'])}", {}),
        "GET /medicines/{code}/rules": lambda: (f"/api/v1/medicines/{rng.choice(s['codes'])}/rules", {}),
        "GET /dispenses (no filter)": lambda: ("/api/v1/dispenses", {}),
        "GET /dispenses?patient_ref": lambda: ("/api/v1/dispenses", {"patient_ref": rng.choice(s["patients"])}),
        "GET /dispenses?medicine_code": lambda: ("/api/v1/dispenses", {"medicine_code": rng.choice(s["codes"])}),
        "GET /dispenses?patient_ref&medicine_code": lambda: (
            "/api/v1/dispenses",
            dict(zip(("patient_ref", "medicine_code"), rng.choice(s["pairs"]), strict=True)),
        ),
        "GET /dispense-attempts": lambda: ("/api/v1/dispense-attempts", {}),
    }


def _pct(values: list[float], p: float) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1]


EXPLAIN_QUERIES = {
    "medicine search (ILIKE %term%)": (
        "SELECT * FROM medicines WHERE name ILIKE :p OR code ILIKE :p ORDER BY name, id LIMIT 21",
        lambda s, rng: {"p": "%" + rng.choice(s["names"]).lower()[2:6] + "%"},
    ),
    "medicines first page": ("SELECT * FROM medicines ORDER BY name, id LIMIT 21", lambda s, rng: {}),
    "patient ledger": (
        "SELECT * FROM dispenses WHERE patient_ref = :p ORDER BY dispensed_at DESC, id DESC LIMIT 21",
        lambda s, rng: {"p": rng.choice(s["patients"])},
    ),
    "dispenses by medicine": (
        "SELECT * FROM dispenses WHERE medicine_id = (SELECT id FROM medicines WHERE code = :c)"
        " ORDER BY dispensed_at DESC, id DESC LIMIT 21",
        lambda s, rng: {"c": rng.choice(s["codes"])},
    ),
    "all dispenses, newest first": ("SELECT * FROM dispenses ORDER BY dispensed_at DESC, id DESC LIMIT 21", lambda s, rng: {}),
    "30-day window read (dispense validation)": (
        "SELECT dispensed_at, quantity FROM dispenses WHERE medicine_id = (SELECT id FROM medicines WHERE code = :c)"
        " AND patient_ref = :p AND dispensed_at >= now() - interval '60 days' AND dispensed_at < now()",
        lambda s, rng: dict(zip(("p", "c"), rng.choice(s["pairs"]), strict=True)),
    ),
}


def explain(s: dict[str, list], rng: random.Random) -> None:
    with get_engine().connect() as conn:
        for label, (sql, params) in EXPLAIN_QUERIES.items():
            plan = conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql), params(s, rng)).scalars().all()
            print(f"\n--- {label}\n" + "\n".join(plan))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("BENCH_BASE_URL", "http://localhost:8000"))
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    rng = random.Random(7)
    samples = _samples()
    with get_engine().connect() as conn:
        counts = {t: conn.scalar(text(f"SELECT count(*) FROM {t}")) for t in ("medicines", "formulary_rules", "dispenses")}

    results = {}
    for label, make in _scenarios(samples, rng).items():
        for _ in range(args.warmup):
            _get(args.base_url, *make())
        timings = []
        for _ in range(args.n):
            ms, status = _get(args.base_url, *make())
            assert status == 200, (label, status)
            timings.append(ms)
        results[label] = {
            "p50": statistics.median(timings),
            "p95": _pct(timings, 95),
            "p99": _pct(timings, 99),
            "max": max(timings),
        }

    if args.json:
        print(json.dumps({"counts": counts, "n": args.n, "results": results}, indent=2))
    else:
        print(f"Dataset: {counts}; {args.n} timed requests per endpoint after {args.warmup} warm-up\n")
        print(f"{'endpoint':45} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}")
        for label, r in results.items():
            flag = "" if r["p95"] < THRESHOLD_MS else "  <-- FAIL"
            print(f"{label:45} {r['p50']:7.1f}ms {r['p95']:7.1f}ms {r['p99']:7.1f}ms {r['max']:7.1f}ms{flag}")
    if args.explain:
        explain(samples, rng)
    worst = max(r["p95"] for r in results.values())
    if worst >= THRESHOLD_MS:
        sys.exit(f"\nFAIL: worst p95 {worst:.1f}ms >= {THRESHOLD_MS}ms")
    print(f"\nPASS: worst p95 {worst:.1f}ms < {THRESHOLD_MS:.0f}ms")


if __name__ == "__main__":
    main()
