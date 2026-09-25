"""Run the safe-memory agent on the Northstar Commerce mock world (github.com/Cioran123/wallymartdata).

Loads one generated scenario, strips the fields that give away the answer (incident_id), turns its alerts into
pages, and scores each page against the scenario's ground_truth.json, which the agent never sees.

  uv run --with anthropic --with duckdb python northstar.py --fake
  uv run --with anthropic --with duckdb python northstar.py --env-file PATH [--agent baseline] [--scenario full_30_day]

Clone the mock world next to this folder, or pass --world PATH.
"""

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import duckdb

from run import BASELINE_ADDENDUM, COMPACT_AT, LLM, Baseline, World, load_key
from safe_memory import MEMORY_ADDENDUM, Fake, SafeAgent, SafeMemory

HERE = Path(__file__).parent
WORLD_REPO = HERE.parent / "wallymartdata"
PT = timedelta(hours=-7)  # narrative time is America/Los_Angeles, which is PDT all of September 2026

# Columns the agent can query, per table. incident_id is left out on purpose: it names which records belong
# to an incident, causes and decoys alike.
TABLES = {
    "alerts": ("alerts.jsonl", ["service", "monitor", "severity", "resolved", "summary"]),
    "logs": ("logs.jsonl", ["service", "level", "code", "message", "request_id"]),
    "deployments": ("deployments.jsonl", ["service", "tag", "previous_tag", "version", "sha", "author",
                                          "commit_subject", "changed_components", "rollback_of"]),
    "config_changes": ("config_changes.jsonl", ["event_type", "service", "actor", "key", "old_value", "new_value",
                                                "action", "summary"]),
    "vendor_snapshots": ("vendor_snapshots.jsonl", ["event_type", "vendor", "page_type", "affected_component",
                                                    "current_status", "previous_status", "changed",
                                                    "extracted_claim", "published_at", "url"]),
    "past_incidents": ("jira_incidents.jsonl", ["ticket_id", "title", "services", "symptoms", "root_cause",
                                                "resolution", "warnings", "status"]),
    "runbooks": ("runbooks.jsonl", ["id", "title", "applies_to", "steps", "notes", "obsolete"]),
}
TOP_LEVEL = {"service", "event_type"}  # these live outside the payload

NORTHSTAR_SYSTEM = """You are the on-call engineer for Northstar Commerce, an online store, during a month-long rotation.

Services: checkout-api calls payment-orchestrator, order-service and inventory-service. payment-orchestrator uses the payments database and the outside payment provider PayRail. search-service serves the catalog. notification-worker sends email and SMS through the vendor Courierly.

You get woken for pages. Investigate with SQL (DuckDB dialect). All timestamps are UTC; local time is PT (UTC-7). Every table holds only records visible by now, and each row has event_id, event_time and visible_at plus:
- alerts: service, monitor, severity, resolved, summary
- metrics (no event_id): service, signal, value, unit. Signals include error_rate, p95_latency_ms, request_count, connection_pool_utilization, connection_pool_wait_ms, payments_db_cpu, payment_success_rate, dependency_latency_ms, cpu, memory. Points are every 15 minutes and arrive about 16 minutes late.
- logs: service, level, code, message, request_id
- deployments: service, tag, previous_tag, version, sha, author, commit_subject, changed_components, rollback_of
- config_changes: event_type, service, actor, key, old_value, new_value, action, summary
- vendor_snapshots: vendor status pages captured by Nimble: event_type, vendor, page_type, affected_component, current_status, previous_status, changed, extracted_claim, published_at, url
- past_incidents: older incident tickets: ticket_id, title, services, symptoms, root_cause, resolution, warnings, status. Some advice in them is obsolete.
- runbooks: id, title, applies_to, steps, notes, obsolete

Then close the page: resolve it with the event_id of the record that caused it (a deployment, a config change, or a vendor snapshot that shows the outside failure), or dismiss it if it is not a real problem. You get at most 15 queries per page and each returns at most 50 rows, so aggregate rather than dumping rows. Stop investigating once the evidence is clear."""


def parse(value):
    return datetime.fromisoformat(value.replace("Z", ""))


def fmt(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")


def when(t):
    local = t + PT
    return f"day {local.day}, {local:%a %Y-%m-%d %H:%M} PT"


def cell(value):
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return "" if value is None else value


def prepare(src, out):
    """Write each table as a flat CSV the World can load, without incident_id."""
    out.mkdir(parents=True, exist_ok=True)
    for table, (filename, columns) in TABLES.items():
        with open(out / f"{table}.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["event_id", "event_time", "visible_at"] + columns)
            for line in (src / filename).read_text().splitlines():
                r = json.loads(line)
                writer.writerow([r["event_id"], fmt(parse(r["event_time"])), fmt(parse(r["visible_at"]))]
                                + [cell(r.get(c) if c in TOP_LEVEL else r["payload"].get(c)) for c in columns])
    with open(src / "metrics.csv") as fin, open(out / "metrics.csv", "w", newline="") as fout:
        writer = csv.writer(fout)
        writer.writerow(["event_time", "visible_at", "service", "signal", "value", "unit"])
        for r in csv.DictReader(fin):
            writer.writerow([fmt(parse(r["event_time"])), fmt(parse(r["visible_at"])), r["service"], r["signal"],
                             r["value"], r["unit"]])
    return out


class NorthstarWorld(World):
    """The scenario's records in DuckDB, every table cut off at visible_at <= now."""

    def __init__(self, data_dir):
        self.db = duckdb.connect()
        self.tables = list(TABLES) + ["metrics"]
        for t in self.tables:
            self.db.execute(f"CREATE TABLE raw_{t} AS SELECT * FROM read_csv_auto('{data_dir / (t + '.csv')}', header=true)")
        self.db.execute("SET enable_external_access = false")
        self.db.execute("SET lock_configuration = true")

    def set_now(self, now):
        for t in self.tables:
            self.db.execute(f"CREATE OR REPLACE TEMP VIEW {t} AS SELECT * FROM raw_{t} WHERE visible_at <= TIMESTAMP '{now}'")


def build_wakeups(src, truth):
    """Pages from firing alerts (grouped when they fire within an hour), plus an 18:00 PT handoff each day."""
    alerts = [json.loads(line) for line in (src / "alerts.jsonl").read_text().splitlines()]
    firing = sorted((a for a in alerts if not a["payload"].get("resolved")), key=lambda a: a["visible_at"])
    groups = []
    for a in firing:
        t = parse(a["visible_at"])
        if groups and t - groups[-1]["start"] <= timedelta(minutes=60):
            groups[-1]["alerts"].append(a)
        else:
            groups.append({"start": t, "alerts": [a]})
    incidents = {i["incident_id"]: i for i in truth["incidents"]}
    wakeups = []
    for k, g in enumerate(groups, 1):
        incident = next((a["incident_id"] for a in g["alerts"] if a["incident_id"]), None)
        label = ({"type": "incident", "incident_id": incident, "cause": incidents[incident]["causal_evidence"],
                  "decoy": incidents[incident]["decoy_evidence"]} if incident else {"type": "noise"})
        wakeups.append({"kind": "page", "page_id": f"p-{k:03d}", "start": fmt(g["start"]), "when": when(g["start"]),
                        "now": fmt(g["start"] + timedelta(minutes=15)), "truth": label,
                        "alerts": [{"ts": fmt(parse(a["visible_at"])), "name": a["payload"]["monitor"],
                                    "service": a["service"], "value": a["payload"].get("severity")} for a in g["alerts"]]})

    changes = [json.loads(line) for f in ("deployments.jsonl", "config_changes.jsonl")
               for line in (src / f).read_text().splitlines()]
    for day in range(1, 31):
        start, end = datetime(2026, 9, day, 7), datetime(2026, 9, day, 7) + timedelta(hours=18)  # 00:00-18:00 PT
        lines = []
        for c in sorted(changes, key=lambda c: c["visible_at"]):
            if start <= parse(c["visible_at"]) <= end:
                p = c["payload"]
                what = (f"{p.get('tag')} \"{p.get('commit_subject')}\" ({p.get('author')})" if c["event_type"] == "deployment"
                        else f"{p.get('key')} {p.get('old_value')} -> {p.get('new_value')} ({p.get('actor')})" if p.get("key")
                        else f"{p.get('action')} ({p.get('actor')})")
                lines.append(f"- {c['event_id']} {(parse(c['event_time']) + PT):%H:%M} PT {c['service']}: {what}")
        pages = [f"{w['page_id']} {w['when'][-8:]} {w['alerts'][0]['name']}" for w in wakeups
                 if w["kind"] == "page" and fmt(start) <= w["start"] <= fmt(end)]
        wakeups.append({"kind": "handoff", "ts": fmt(end),
                        "text": f"End-of-day handoff, {when(end)}\nChanges today:\n" + ("\n".join(lines) or "- none")
                                + "\nPages today: " + ("; ".join(pages) or "none")})
    return sorted(wakeups, key=lambda w: w["start"] if w["kind"] == "page" else w["ts"])


def score(w, outcome):
    kind, args = outcome
    truth = w["truth"]
    if truth["type"] == "noise":
        return "correct" if kind == "dismiss" else "false alarm"
    if kind != "resolve":
        return "missed" if kind == "dismiss" else kind
    got = args["cause_event_id"].strip()
    return "correct" if got in truth["cause"] else "decoy" if got in truth["decoy"] else "wrong"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="full_30_day", choices=["smoke_internal", "smoke_vendor", "full_30_day"])
    ap.add_argument("--agent", default="safe", choices=["safe", "baseline"])
    ap.add_argument("--world", type=Path, default=WORLD_REPO, help="path to the wallymartdata checkout")
    ap.add_argument("--fake", action="store_true", help="no API calls")
    ap.add_argument("--env-file", help="read ANTHROPIC_API_KEY from this file")
    args = ap.parse_args()
    if args.env_file:
        load_key(args.env_file)
    src = args.world / "mockworld" / "generated" / args.scenario
    truth = json.loads((src / "ground_truth.json").read_text())
    wakeups = build_wakeups(src, truth)
    pages = [w for w in wakeups if w["kind"] == "page"]
    print(f"{args.scenario}: {len(pages)} pages ({sum(w['truth']['type'] == 'incident' for w in pages)} incidents), "
          f"{len(wakeups) - len(pages)} handoffs", flush=True)

    # A dropped connection otherwise waits out the SDK default of 10 minutes per attempt.
    client = Fake() if args.fake else anthropic.Anthropic(base_url="https://api.anthropic.com", timeout=180.0, max_retries=4)
    world = NorthstarWorld(prepare(src, HERE / "northstar_data" / args.scenario))
    name = f"northstar_{args.scenario}_{args.agent}"
    if args.agent == "safe":
        agent = SafeAgent(LLM(client), world, SafeMemory(HERE / "results" / f"{name}_memory.jsonl"),
                          system=NORTHSTAR_SYSTEM + MEMORY_ADDENDUM)
    else:
        agent = Baseline(LLM(client), world, 3000 if args.fake else COMPACT_AT, system=NORTHSTAR_SYSTEM + BASELINE_ADDENDUM)
    rows = []
    for w in wakeups:
        agent.llm.tag = {"t": w["start"] if w["kind"] == "page" else w["ts"], "wake": w.get("page_id", "handoff")}
        if w["kind"] == "handoff":
            agent.handoff(w)
            continue
        outcome, queries = agent.page(w)
        result = score(w, outcome)
        rows.append({"page_id": w["page_id"], "when": w["when"], "truth": w["truth"], "action": outcome[0],
                     "answer": outcome[1].get("cause_event_id") or outcome[1].get("reason", ""), "result": result,
                     "queries": queries})
        tag = f" [{w['truth']['incident_id']}]" if w["truth"]["type"] == "incident" else ""
        print(f"{w['page_id']} ({w['when']}) {w['truth']['type']}{tag}: {outcome[0]} "
              f"{rows[-1]['answer'][:40]!r} -> {result} ({queries} queries)", flush=True)

    llm = agent.llm
    totals = {"pages": len(rows), "correct": sum(r["result"] == "correct" for r in rows),
              "queries": sum(r["queries"] for r in rows), "calls": llm.calls, "max_context": llm.max_context,
              "cost": round(llm.cost, 2)}
    carried = agent.memory.read() if args.agent == "safe" else "\n\n".join(agent.summaries)
    (HERE / "results" / f"{name}.json").write_text(
        json.dumps({"agent": args.agent, "totals": totals, "pages": rows, "carried_forward": carried, "trace": llm.trace}, indent=1))
    print(f"\nCARRIED FORWARD\n{carried}\n\nTOTALS: {totals['correct']}/{totals['pages']} correct, "
          f"{totals['queries']} queries, {totals['calls']} model calls, largest context {totals['max_context']:,} tokens, "
          f"${totals['cost']:.2f}")


if __name__ == "__main__":
    main()
