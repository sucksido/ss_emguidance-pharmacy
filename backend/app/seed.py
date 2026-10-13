"""Load a deterministic demo/performance dataset.

    python -m app.seed                 # 500 medicines, ~2,000 rules, 5,000 dispenses, 2,150 patients
    python -m app.seed --scale 10      # ten times that, for the "what at 10x?" question

Every generated dispense is passed through the real rule engine
(app.domain.rules_engine.evaluate) against the dispenses generated before it,
in RANDOM time order - so the seed both obeys every business rule and
exercises the backdated-dispense logic thousands of times. Rows are then
bulk-inserted; going through HTTP would add minutes and prove nothing extra.

The command replaces existing data (TRUNCATE) so it is safe to re-run.
"""

from __future__ import annotations

import argparse
import random
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import insert, text

from app.db import get_engine
from app.domain import rules_engine as engine
from app.models import Dispense, FormularyRule, Medicine
from app.timeutil import business_date, start_of_business_day_utc

SYLLABLES = ["zen", "tra", "pro", "fen", "lor", "max", "cil", "dol", "vir", "sta", "mo", "xa", "ri", "ta", "neb",
             "olol", "pril", "tine", "azole", "mab", "cort", "lin", "pam", "vas", "ur", "ide", "en", "ox", "al"]
FORMS = {"tablet": "mg", "capsule": "mg", "suspension": "mg/5ml", "injection": "mg/ml", "cream": "%", "inhaler": "mcg"}
STRENGTHS = [1, 2.5, 5, 10, 20, 25, 50, 100, 125, 200, 250, 400, 500, 850, 1000]
PER_DISPENSE = [10, 14, 20, 28, 30, 56, 60, 90, 100]


def _name(rng: random.Random) -> str:
    return "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3))).capitalize()


def build(scale: int, seed: int, today: date, now: datetime):
    rng = random.Random(seed)
    n_meds, n_singletons, n_regulars, n_dispenses = 500 * scale, 2000 * scale, 150 * scale, 5000 * scale

    medicines, rules_by_med = [], {}
    rule_id = 0
    for i in range(1, n_meds + 1):
        form = rng.choice(list(FORMS))
        strength = Decimal(str(rng.choice(STRENGTHS)))
        medicines.append(
            {
                "id": i,
                "code": f"MED{i:06d}",
                "name": f"{_name(rng)} {strength.normalize():f} {FORMS[form]} {form}",
                "form": form,
                "strength_value": strength,
                "strength_unit": FORMS[form],
                "is_active": rng.random() > 0.05,
            }
        )
        # 3-5 contiguous periods covering the last ~2 years; ~15% have a change scheduled in future.
        k = rng.randint(3, 5)
        start = today - timedelta(days=760 + rng.randint(0, 30))
        future_change = rng.random() < 0.15
        end_known = today + timedelta(days=rng.randint(10, 90)) if future_change else today - timedelta(days=rng.randint(10, 60))
        inner = sorted(rng.sample(range(1, (end_known - start).days), k - 2)) if k > 2 else []
        bounds = [start] + [start + timedelta(days=d) for d in inner] + [end_known, None]
        med_rules = []
        for frm, to in zip(bounds[:-1], bounds[1:], strict=True):
            rule_id += 1
            per = rng.choice(PER_DISPENSE)
            med_rules.append(
                engine.RuleFacts(rule_id, frm, to, per, per * rng.choice([2, 3, 4]), rng.random() < 0.1)
            )
        rules_by_med[i] = med_rules

    active = [m for m in medicines if m["is_active"]]
    singletons = [f"PT-{n:07d}" for n in range(1, n_singletons + 1)]
    regulars = [f"PT-R{n:06d}" for n in range(1, n_regulars + 1)]
    favourites = {p: rng.sample(active, rng.randint(1, 3)) for p in regulars}

    span = int((now - start_of_business_day_utc(today - timedelta(days=730))).total_seconds())
    window_start = now - timedelta(seconds=span)
    history: dict[tuple[str, int], list[engine.PriorDispense]] = defaultdict(list)
    dispenses = []
    plan = [(p, rng.choice(active)) for p in singletons]
    while len(plan) < n_dispenses * 2:  # oversupply; some candidates will be rejected
        p = rng.choice(regulars)
        plan.append((p, rng.choice(favourites[p])))
    rng.shuffle(plan)
    plan.sort(key=lambda x: not x[0].startswith("PT-0"))  # singletons first so each gets one
    rejected = 0
    for patient, med in plan:
        if len(dispenses) >= n_dispenses:
            break
        at = window_start + timedelta(seconds=rng.randint(0, span - 1))
        at = at.replace(microsecond=0)
        rule = engine.rule_in_force(rules_by_med[med["id"]], business_date(at))
        if rule is None:
            rejected += 1
            continue
        qty = rng.randint(1, rule.max_quantity_per_dispense)
        auth = f"AUTH-{rng.randint(100000, 999999)}" if rule.requires_authorisation else None
        cand = engine.Candidate(med["code"], patient, qty, at, auth)
        lo, hi = engine.history_horizon(business_date(at))
        prior = [h for h in history[(patient, med["id"])] if lo <= h.business_date <= hi]
        ev = engine.evaluate(cand, engine.MedicineFacts(med["id"], med["code"], True), rules_by_med[med["id"]], prior, now)
        if not ev.accepted:
            rejected += 1
            continue
        history[(patient, med["id"])].append(engine.PriorDispense(ev.business_date, qty))
        dispenses.append(
            {
                "medicine_id": med["id"],
                "formulary_rule_id": ev.governing_rule.id,
                "patient_ref": patient,
                "quantity": qty,
                "dispensed_at": at,
                "authorisation_ref": auth,
                "idempotency_key": f"seed-{len(dispenses) + 1:08d}",
                "recorded_at": now,
                "recorded_by": "seed",
            }
        )

    rules = [
        {
            "id": r.id,
            "medicine_id": mid,
            "effective_from": r.effective_from,
            "effective_to": r.effective_to,
            "max_quantity_per_dispense": r.max_quantity_per_dispense,
            "max_quantity_per_30_days": r.max_quantity_per_30_days,
            "requires_authorisation": r.requires_authorisation,
            "created_by": "seed",
        }
        for mid, rs in rules_by_med.items()
        for r in rs
    ]
    # Record supersession links for history display.
    by_id = {r["id"]: r for r in rules}
    for rs in rules_by_med.values():
        for a, b in zip(rs, rs[1:], strict=False):
            by_id[a.id]["superseded_by_id"] = b.id
        by_id[rs[-1].id]["superseded_by_id"] = None
    return medicines, rules, dispenses, rejected


# Re-checks rule 3 for every seeded dispense in SQL, independently of the Python engine.
VERIFY_SQL = """
WITH daily AS (
    SELECT patient_ref, medicine_id,
           (dispensed_at AT TIME ZONE 'Africa/Johannesburg')::date AS day,
           sum(quantity) AS qty, max(quantity) AS biggest, max(formulary_rule_id) AS rule_id
      FROM dispenses
     GROUP BY 1, 2, 3
), windowed AS (
    SELECT *, sum(qty) OVER (
               PARTITION BY patient_ref, medicine_id ORDER BY day
               RANGE BETWEEN '29 days'::interval PRECEDING AND CURRENT ROW) AS window_qty
      FROM daily
)
SELECT count(*)
  FROM windowed w JOIN formulary_rules r ON r.id = w.rule_id
 WHERE w.biggest > r.max_quantity_per_dispense OR w.window_qty > r.max_quantity_per_30_days
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--seed", type=int, default=20260901)
    args = ap.parse_args()

    now = datetime.now(UTC)
    today = business_date(now)
    t0 = time.perf_counter()
    medicines, rules, dispenses, rejected = build(args.scale, args.seed, today, now)
    t1 = time.perf_counter()

    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE dispense_attempts, dispenses, formulary_rules, medicines RESTART IDENTITY CASCADE"))
        conn.execute(insert(Medicine.__table__), medicines)
        # Identity columns are GENERATED BY DEFAULT, so explicit ids are accepted;
        # the sequences are advanced past them below.
        links = [{"rid": r["id"], "sid": r["superseded_by_id"]} for r in rules if r["superseded_by_id"]]
        conn.execute(insert(FormularyRule.__table__), [{**r, "superseded_by_id": None} for r in rules])
        conn.execute(text("UPDATE formulary_rules SET superseded_by_id = :sid WHERE id = :rid"), links)
        for i in range(0, len(dispenses), 5000):
            conn.execute(insert(Dispense.__table__), dispenses[i : i + 5000])
        for table in ("medicines", "formulary_rules", "dispenses"):
            conn.execute(
                text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT max(id) FROM {table}))")
            )
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM ANALYZE"))
    t2 = time.perf_counter()
    with eng.connect() as conn:
        breaches = conn.scalar(text(VERIFY_SQL))

    patients = len({d["patient_ref"] for d in dispenses})
    days = {business_date(d["dispensed_at"]) for d in dispenses}
    print(
        f"Seeded {len(medicines)} medicines, {len(rules)} rules "
        f"({len(rules) / len(medicines):.1f}/medicine), {len(dispenses)} dispenses across {patients} patient refs, "
        f"{min(days)} .. {max(days)}.\n"
        f"Independent SQL re-check of every 30-day window: {breaches} breaches.\n"
        f"Generated in {t1 - t0:.1f}s ({rejected} candidates rejected by the rule engine), loaded in {t2 - t1:.1f}s."
    )


if __name__ == "__main__":
    main()
