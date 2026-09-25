"""Assemble the data for the experiment dashboard: both agents' 30-day Northstar runs, page by page."""

import json
from pathlib import Path

from build_dashboard import day, peaks
from northstar import WORLD_REPO, build_wakeups

HERE = Path(__file__).parent
R = HERE / "results"
SRC = WORLD_REPO / "mockworld" / "generated" / "full_30_day"

STORY = {
    "inc-day-04": {"title": "Payments connection limit cut",
                   "what": "At 02:00 PT a cost bot cut payments.max_connections from 100 to 20. Nothing broke until lunch traffic arrived. A harmless checkout copy deploy landed at 11:40, 25 minutes before the alert: the decoy.",
                   "cause": "config-day04-reduce", "decoy": "deploy-day04-decoy"},
    "inc-day-09": {"title": "PayRail outage the status page hid",
                   "what": "PayRail's US West API started failing while its status page still said operational. The first snapshot admitting it (captured by Nimble) appeared at 12:20 PT. A receipt-footer deploy at 11:50 was the decoy.",
                   "cause": "vendor-payrail-20260909T192000Z", "decoy": "deploy-day09-decoy"},
    "inc-day-22": {"title": "The same cut, 18 days later",
                   "what": "The cost bot cut the connection limit to 20 again at 02:00 PT, with another harmless checkout deploy just before the alert. Nothing about day 4 was pre-seeded; any lesson is the agent's own.",
                   "cause": "config-day22-reduce", "decoy": "deploy-day22-decoy"},
    "inc-day-24": {"title": "Look-alike with a different cause",
                   "what": "Pool timeouts again, but the connection limit was unchanged and database CPU was high. The cause was payment-orchestrator v9.4.2, whose new enrichment query holds a pool connection. An old ticket's advice to raise the limit is obsolete, and a log-level change at 10:05 was the decoy.",
                   "cause": "deploy-day24-enrichment", "decoy": "config-day24-log-level"},
}


def main():
    truth = json.loads((SRC / "ground_truth.json").read_text())
    wakeups = build_wakeups(SRC, truth)
    base = json.loads((R / "northstar_full_30_day_baseline.json").read_text())
    safe = json.loads((R / "northstar_full_30_day.json").read_text())  # the full first run of the memory agent
    rerun_path = R / "northstar_full_30_day_safe.json"
    rerun = json.loads(rerun_path.read_text()) if rerun_path.exists() else None
    if rerun and rerun["totals"]["max_context"] < 2000:  # a leftover fake-model check, not a real run
        rerun = None

    log = [json.loads(line) for line in (R / "northstar_full_30_day_memory.jsonl").read_text().splitlines()]
    edits_at, entries, mem_series = {}, {}, []
    for e in log:
        if e["result"].startswith("refused"):
            continue
        key = e["result"].split()[-1]
        if e["op"] == "add_entry":
            entries[key] = e["args"]["text"]
        elif e["op"] == "update_entry":
            entries[key] = e["args"]["text"]
        else:
            entries.pop(key, None)
        edits_at.setdefault(e["when"], []).append({"op": e["op"].split("_")[0], "id": key,
                                                   "text": e["args"].get("text") or e["args"].get("reason", ""),
                                                   "evidence": e["args"].get("evidence", [])})
        mem_series.append({"day": day(e["when"]), "n": len(entries)})

    base_series, resets = peaks(base["trace"])
    base_by_wake = {p["wake"]: p for p in base_series if p["wake"] != "handoff"}
    rows_b = {p["page_id"]: p for p in base["pages"]}
    rows_s = {p["page_id"]: p for p in safe["pages"]}
    pages = []
    for w in wakeups:
        if w["kind"] != "page":
            continue
        pid, inc = w["page_id"], w["truth"].get("incident_id")
        bp = base_by_wake.get(pid)
        pages.append({
            "id": pid, "day": day(w["start"]), "when": w["when"], "incident": inc,
            "monitor": w["alerts"][0]["name"], "service": w["alerts"][0]["service"],
            "naive": {k: rows_b[pid][k] for k in ("action", "answer", "result", "queries")} | {"context": bp["peak"] if bp else None},
            "memory": {k: rows_s[pid][k] for k in ("action", "answer", "result", "queries")},
            "edits": edits_at.get(w["start"], []),
            "summarized": bool(bp) and any(abs(r - bp["day"]) < 1e-6 for r in resets),
        })
    data = {
        "pages": pages, "story": STORY, "memory": mem_series, "final_memory": safe["memory"],
        "naive_context": [{"day": p["day"], "v": p["peak"]} for p in base_series],
        "resets": resets,
        "memory_context": [{"day": p["day"], "v": p["peak"]} for p in peaks(rerun["trace"])[0]] if rerun else None,
        "totals": {"naive": base["totals"], "memory": safe["totals"]},
    }
    html = (HERE / "story_template.html").read_text().replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
    out = HERE.parent / "experiment-dashboard.html"
    out.write_text(html)
    print(f"wrote {out.name} ({len(html) // 1024} KB); memory context line: {'yes' if rerun else 'not yet'}")


if __name__ == "__main__":
    main()
