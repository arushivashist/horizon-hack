"""Synthetic on-call world for the first-hour test.

Writes data/{metrics,logs,deploys,config_changes,alerts}.csv and data/wakeups.json
(pages with ground truth, plus end-of-day handoff notes) for days 1..DAYS.

Planted:
- Day 4: the cost bot shrinks the payments DB pool at 2am; checkout breaks at the
  lunch peak. Decoy: a harmless checkout deploy 20 minutes before the alert.
- Day 12: same bot, inventory pool this time; the first alert is the same
  inventory_p99_high that fires as noise every night. Decoy: an inventory deploy.
- Every night: a 3am inventory batch job trips inventory_p99_high for ~15 minutes.
Alerts come from threshold rules on the metrics, not from hand placement.
"""

import csv
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

DAYS = 12
SEED = 7
START = datetime(2026, 8, 31)  # day 1, a Monday
OUT = Path(__file__).parent / "data"
rng = random.Random(SEED)

# name: (peak rps, base p99 ms, base error rate)
SERVICES = {
    "web": (400, 180, 0.003),
    "checkout": (120, 350, 0.002),
    "payments": (100, 250, 0.001),
    "inventory": (150, 120, 0.001),
    "search": (250, 150, 0.002),
}
DB_HOLD_S = {"payments": 0.25, "inventory": 0.15}  # seconds each request holds a DB connection
DEFAULT_POOL = {"payments": 50, "inventory": 40}
BOT = "cost-optimizer-bot"

# (day, hh, mm, service, key, old, new, author)
CONFIG = [
    (1, 15, 10, "web", "rate_limit_rps", "800", "1000", "eli"),
    (2, 2, 0, "search", "replica_count", "6", "5", BOT),
    (3, 14, 20, "checkout", "feature_gift_cards", "false", "true", "farah"),
    (4, 2, 0, "payments", "db_pool_max", "50", "20", BOT),  # cause of the day-4 incident
    (4, 12, 40, "payments", "db_pool_max", "20", "50", "alice"),  # the fix
    (5, 16, 5, "payments", "retry_backoff_ms", "200", "250", "gus"),
    (7, 2, 0, "checkout", "worker_threads", "16", "12", BOT),
    (8, 11, 30, "search", "synonyms_version", "v12", "v13", "hana"),
    (9, 2, 0, "web", "cache_ttl_s", "60", "45", BOT),
    (10, 2, 0, "redis", "maxmemory_mb", "4096", "3584", BOT),
    (11, 15, 45, "inventory", "reservation_ttl_s", "600", "900", "dana"),
    (12, 2, 0, "inventory", "db_pool_max", "40", "15", BOT),  # cause of the day-12 incident
    (12, 12, 30, "inventory", "db_pool_max", "15", "40", "bob"),  # the fix
]
DECOYS = {4: ("checkout", "tweak retry logging", "dana"), 12: ("inventory", "add stock reservation metrics", "eli")}
DEPLOY_MESSAGES = [
    "bump dependencies",
    "add request tracing spans",
    "refactor handler for readability",
    "fix typo in order email template",
    "improve error messages",
    "update feature flag client",
    "add unit tests for pricing",
    "clean up dead code",
]
PEOPLE = ["dana", "eli", "farah", "gus", "hana"]
VERSIONS = {"web": [3, 12, 0], "checkout": [1, 4, 0], "payments": [2, 2, 0], "inventory": [2, 7, 0], "search": [1, 9, 0]}

# (alert name, service, metric, threshold, minutes over threshold before firing / under before resolving)
RULES = [
    ("checkout_error_rate_high", "checkout", "error_rate", 0.02, 5),
    ("checkout_p99_high", "checkout", "p99_ms", 1500, 5),
    ("payments_p99_high", "payments", "p99_ms", 1500, 5),
    ("inventory_p99_high", "inventory", "p99_ms", 800, 3),
    ("web_error_rate_high", "web", "error_rate", 0.02, 5),
    ("search_p99_high", "search", "p99_ms", 800, 5),
]

BACKGROUND_ERRORS = {
    "web": ["client disconnected before response", "GET /product/{n} returned 404"],
    "checkout": ["cart validation failed: missing shipping zip", "coupon {n} not found"],
    "payments": ["card declined by issuer (code 05)", "duplicate idempotency key"],
    "inventory": ["sku {n} not found", "stock level race detected, retried"],
    "search": ["query parse error near position {n}", "empty result for filtered query"],
}
BACKGROUND_WARNS = ["retrying upstream call (attempt 2/3)", "slow request {n}ms on GET /api", "request body larger than 1MB"]


def at(day, hh, mm=0):
    return START + timedelta(days=day - 1, hours=hh, minutes=mm)


def fmt(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")


def when(t):
    day = (t - START).days + 1
    return f"day {day}, {t:%a %Y-%m-%d %H:%M}"


def shape(t):
    """Traffic as a fraction of peak: lunch peak, small evening bump, quieter weekends."""
    h = t.hour + t.minute / 60
    s = 0.15 + 0.85 * math.exp(-(((h - 12.75) / 2.6) ** 2)) + 0.25 * math.exp(-(((h - 19.5) / 1.5) ** 2))
    return s * (0.6 if t.weekday() >= 5 else 1.0)


def saturation(u):
    """Extra wait (ms) and timeout error rate for a DB pool at utilization u."""
    wait = 3000 * min(max((u - 0.9) / 0.4, 0), 1)
    err = 0.5 * min(max((u - 1.0) / 0.5, 0), 1)
    return wait, err


def poisson(lam):
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def main():
    OUT.mkdir(exist_ok=True)
    minutes = DAYS * 1440
    config = sorted(({"ts": at(d, h, m), "service": s, "key": k, "old": o, "new": n, "author": a}
                     for d, h, m, s, k, o, n, a in CONFIG), key=lambda c: c["ts"])

    # --- metrics, one row per service per minute ---
    pool = dict(DEFAULT_POOL)
    pending_config = list(config)
    metrics, series, state = [], {}, []  # state[i] keeps per-minute causes for the log writer
    for i in range(minutes):
        t = START + timedelta(minutes=i)
        while pending_config and pending_config[0]["ts"] <= t:
            c = pending_config.pop(0)
            if c["key"] == "db_pool_max":
                pool[c["service"]] = int(c["new"])
        s = shape(t)
        rps = {n: peak * s * rng.gauss(1, 0.03) for n, (peak, _, _) in SERVICES.items()}
        p99 = {n: base * rng.gauss(1, 0.06) for n, (_, base, _) in SERVICES.items()}
        err = {n: e * max(rng.gauss(1, 0.15), 0) for n, (_, _, e) in SERVICES.items()}
        conns, extra_err, wait = {}, {}, {}
        for svc in DB_HOLD_S:
            need = rps[svc] * DB_HOLD_S[svc]
            wait[svc], extra_err[svc] = saturation(need / pool[svc])
            p99[svc] += wait[svc]
            err[svc] += extra_err[svc]
            conns[svc] = pool[svc] if need >= pool[svc] else need * rng.gauss(1, 0.05)
        batch = t.hour == 3 and t.minute < 12
        if batch:
            p99["inventory"] += 1000 * rng.gauss(1, 0.08)
        # propagate along the call graph (the batch job runs when checkout is idle, so it doesn't propagate)
        p99["checkout"] += 0.8 * wait["payments"] + 0.9 * wait["inventory"]
        err["checkout"] += 0.9 * extra_err["payments"] + 0.6 * extra_err["inventory"]
        checkout_extra_err = 0.9 * extra_err["payments"] + 0.6 * extra_err["inventory"]
        p99["web"] += 0.3 * (0.8 * wait["payments"] + 0.9 * wait["inventory"])
        err["web"] += 0.35 * checkout_extra_err
        cpu = {n: 20 + 40 * s + rng.gauss(0, 3) for n in SERVICES}
        for n in SERVICES:
            row = {"ts": fmt(t), "service": n, "rps": round(rps[n], 1), "error_rate": round(err[n], 4),
                   "p99_ms": round(p99[n]), "db_conn_in_use": round(conns[n]) if n in conns else "",
                   "cache_hit_rate": round(min(rng.gauss(0.92, 0.01), 0.99), 3) if n == "search" else "",
                   "cpu_pct": round(cpu[n], 1)}
            metrics.append(row)
            series.setdefault((n, "p99_ms"), []).append(row["p99_ms"])
            series.setdefault((n, "error_rate"), []).append(row["error_rate"])
        metrics.append({"ts": fmt(t), "service": "postgres", "rps": round((rps["payments"] + rps["inventory"]) * 3, 1),
                        "error_rate": 0, "p99_ms": round((40 if batch else 8) * rng.gauss(1, 0.1)), "db_conn_in_use": "",
                        "cache_hit_rate": "", "cpu_pct": round(25 + 40 * s + (45 if batch else 0) + rng.gauss(0, 3), 1)})
        metrics.append({"ts": fmt(t), "service": "redis", "rps": round(rps["search"] * 2.5 + rps["web"] * 0.5, 1),
                        "error_rate": 0, "p99_ms": round(1.5 * rng.gauss(1, 0.1), 1), "db_conn_in_use": "",
                        "cache_hit_rate": "", "cpu_pct": round(12 + 20 * s + rng.gauss(0, 2), 1)})
        state.append({"t": t, "rps": rps, "err": err, "p99": p99, "wait": wait, "extra_err": extra_err,
                      "checkout_extra_err": checkout_extra_err, "batch": batch})

    # --- alerts from threshold rules ---
    alerts = []
    for name, svc, metric, threshold, n in RULES:
        values, firing, over, under = series[(svc, metric)], False, 0, 0
        for i, v in enumerate(values):
            over, under = (over + 1, 0) if v > threshold else (0, under + 1)
            if not firing and over == n:
                firing = True
                alerts.append({"ts": START + timedelta(minutes=i), "alert_name": name, "service": svc, "state": "firing", "value": v})
            elif firing and under == n:
                firing = False
                alerts.append({"ts": START + timedelta(minutes=i), "alert_name": name, "service": svc, "state": "resolved", "value": v})
    alerts.sort(key=lambda a: a["ts"])
    for k, a in enumerate(alerts, 1):
        a["alert_id"] = f"a-{k:03d}"

    # --- pages: firing alerts within an hour of a page's first alert join that page ---
    pages = []
    for a in (a for a in alerts if a["state"] == "firing"):
        if pages and a["ts"] - pages[-1]["start"] <= timedelta(minutes=60):
            pages[-1]["alerts"].append(a)
        else:
            pages.append({"start": a["ts"], "alerts": [a]})

    # --- deploys: decoys 20 minutes before each incident page, harmless ones elsewhere ---
    deploys = []
    for p in pages:
        day = (p["start"] - START).days + 1
        if day in DECOYS and 9 <= p["start"].hour < 16:
            svc, msg, who = DECOYS[day]
            deploys.append({"ts": p["start"] - timedelta(minutes=20), "service": svc, "message": msg, "author": who, "decoy_for": day})
    for day in range(1, DAYS + 1):
        busy_morning = day in DECOYS
        for _ in range(rng.choice([2, 3, 4]) if at(day, 0).weekday() < 5 else rng.choice([0, 1])):
            lo = 13 * 60 + 30 if busy_morning else 10 * 60
            minute = rng.randrange(lo, 17 * 60, 5)
            deploys.append({"ts": at(day, 0) + timedelta(minutes=minute), "service": rng.choice(list(SERVICES)),
                            "message": rng.choice(DEPLOY_MESSAGES), "author": rng.choice(PEOPLE)})
    deploys.sort(key=lambda d: d["ts"])
    for k, d in enumerate(deploys, 1):
        d["event_id"] = f"dep-{k:03d}"
        v = VERSIONS[d["service"]]
        v[2] += 1
        d["version"] = "v" + ".".join(map(str, v))
    for k, c in enumerate(config, 1):
        c["event_id"] = f"cfg-{k:03d}"

    # --- logs derived from the same per-minute state ---
    logs = []
    for st in state:
        t = st["t"]
        for svc in SERVICES:
            lam = min(st["err"][svc] * st["rps"][svc] * 60 * 0.002, 30)
            for _ in range(poisson(lam)):
                msg = None
                if rng.random() > 0.2:
                    if svc in DB_HOLD_S and st["extra_err"][svc] > 0.01:
                        msg = "request timed out after 3000ms waiting for db connection"
                    elif svc == "checkout" and st["extra_err"]["payments"] > 0.01:
                        msg = "payment authorization failed: upstream payments timeout after 3000ms"
                    elif svc == "checkout" and st["extra_err"]["inventory"] > 0.01:
                        msg = "inventory reservation failed: upstream timeout after 3000ms"
                    elif svc == "web" and st["checkout_extra_err"] > 0.01:
                        msg = "POST /checkout returned 502 from upstream checkout"
                msg = msg or rng.choice(BACKGROUND_ERRORS[svc]).format(n=rng.randint(100, 999))
                logs.append({"ts": t + timedelta(seconds=rng.randint(0, 59)), "service": svc, "level": "ERROR", "message": msg})
            for _ in range(poisson(lam * 1.5)):
                msg = None
                if svc in DB_HOLD_S and st["wait"][svc] > 200:
                    msg = f"slow db acquire: waited {int(st['wait'][svc] * rng.uniform(0.6, 1.0))}ms for a connection"
                elif svc == "checkout" and st["wait"]["payments"] > 300:
                    msg = f"payments call slow: {int(st['p99']['payments'])}ms"
                elif svc == "checkout" and st["wait"]["inventory"] > 300:
                    msg = f"inventory reservation slow: {int(st['p99']['inventory'])}ms"
                msg = msg or rng.choice(BACKGROUND_WARNS).format(n=rng.randint(900, 1900))
                logs.append({"ts": t + timedelta(seconds=rng.randint(0, 59)), "service": svc, "level": "WARN", "message": msg})
        if t.hour == 3 and t.minute == 0:
            logs.append({"ts": t, "service": "inventory-batch", "level": "INFO", "message": "reindex job started"})
        if t.hour == 3 and t.minute == 12:
            logs.append({"ts": t, "service": "inventory-batch", "level": "INFO", "message": "reindex job completed in 12m"})
    for d in deploys:
        logs.append({"ts": d["ts"], "service": d["service"], "level": "INFO", "message": f"starting version {d['version']}"})
    logs.sort(key=lambda r: r["ts"])

    # --- ground truth per page ---
    causes = [c for c in config if c["key"] == "db_pool_max" and c["author"] == BOT]
    fixes = [c for c in config if c["key"] == "db_pool_max" and c["author"] != BOT]
    wakeups = []
    for k, p in enumerate(pages, 1):
        truth, day = None, (p["start"] - START).days + 1
        if p["start"].hour == 3 and p["start"].minute < 30:
            truth = {"type": "noise"}  # the batch job; a shrunk pool doesn't bite at 3am traffic
        for cause, fix in zip(causes, fixes):
            if truth is None and cause["ts"] <= p["start"] <= fix["ts"]:
                decoy = next(d for d in deploys if d.get("decoy_for") == day)
                truth = {"type": "incident", "cause_event_id": cause["event_id"], "decoy_event_id": decoy["event_id"]}
        if truth is None:
            raise SystemExit(f"unexpected page at {p['start']}: {[a['alert_name'] for a in p['alerts']]}")
        wakeups.append({"kind": "page", "page_id": f"p-{k:03d}", "start": fmt(p["start"]), "when": when(p["start"]),
                        "now": fmt(p["start"] + timedelta(minutes=15)), "truth": truth,
                        "alerts": [{"alert_id": a["alert_id"], "ts": fmt(a["ts"]), "name": a["alert_name"],
                                    "service": a["service"], "value": a["value"]} for a in p["alerts"]]})
    for day in range(1, DAYS + 1):
        t0, t1 = at(day, 0), at(day, 18)
        dep = [f"- {d['event_id']} {d['ts']:%H:%M} {d['service']} {d['version']} \"{d['message']}\" ({d['author']})"
               for d in deploys if t0 <= d["ts"] <= t1]
        cfg = [f"- {c['event_id']} {c['ts']:%H:%M} {c['service']}.{c['key']} {c['old']} -> {c['new']} ({c['author']})"
               for c in config if t0 <= c["ts"] <= t1]
        pg = [f"{w['page_id']} {w['start'][11:16]} {w['alerts'][0]['name']}" for w in wakeups
              if w["kind"] == "page" and fmt(t0) <= w["start"] <= fmt(t1)]
        text = (f"End-of-day handoff, {when(t1)}\nDeploys today:\n" + ("\n".join(dep) or "- none")
                + "\nConfig changes today:\n" + ("\n".join(cfg) or "- none")
                + "\nPages today: " + ("; ".join(pg) or "none"))
        wakeups.append({"kind": "handoff", "ts": fmt(t1), "text": text})
    wakeups.sort(key=lambda w: w["start"] if w["kind"] == "page" else w["ts"])

    # --- write ---
    def write(name, rows, cols):
        with open(OUT / f"{name}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: fmt(v) if isinstance(v, datetime) else v for k, v in r.items()})

    write("metrics", metrics, ["ts", "service", "rps", "error_rate", "p99_ms", "db_conn_in_use", "cache_hit_rate", "cpu_pct"])
    write("logs", logs, ["ts", "service", "level", "message"])
    write("deploys", deploys, ["event_id", "ts", "service", "version", "author", "message"])
    cfg_rows = [{"event_id": c["event_id"], "ts": c["ts"], "service": c["service"], "key": c["key"],
                 "old_value": c["old"], "new_value": c["new"], "author": c["author"]} for c in config]
    write("config_changes", cfg_rows, ["event_id", "ts", "service", "key", "old_value", "new_value", "author"])
    write("alerts", alerts, ["alert_id", "ts", "alert_name", "service", "state", "value"])
    (OUT / "wakeups.json").write_text(json.dumps(wakeups, indent=1))

    print(f"{len(metrics)} metric rows, {len(logs)} log lines, {len(deploys)} deploys, {len(config)} config changes, {len(alerts)} alert events")
    for w in wakeups:
        if w["kind"] == "page":
            names = ", ".join(f"{a['name']}@{a['ts'][11:16]}" for a in w["alerts"])
            print(f"{w['page_id']} {w['when']}: {names} -> {w['truth']}")


if __name__ == "__main__":
    main()
