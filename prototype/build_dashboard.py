"""Turn the two instrumented Northstar runs into the data block the dashboard page renders."""

import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"
TEMPLATE = HERE / "dashboard_template.html"
OUT = HERE.parent / "northstar-dashboard.html"
START_PT = datetime(2026, 9, 1)  # day 1, 00:00 PT
PT = timedelta(hours=-7)
INCIDENTS = {
    "inc-day-04": "Cost bot cut the payments connection limit to 20 overnight",
    "inc-day-09": "PayRail failed before its status page admitted it",
    "inc-day-22": "The same connection-limit cut, 18 days later",
    "inc-day-24": "Look-alike: pool timeouts from a new enrichment query, limit unchanged",
}


def day(t):
    """UTC timestamp string -> fractional day of the month in PT (1.0 = day 1, 00:00)."""
    return round((datetime.fromisoformat(t) + PT - START_PT).total_seconds() / 86400 + 1, 4)


def peaks(trace):
    """Largest context per wake-up, in wake-up order, plus the wake-ups where the baseline summarized."""
    order, peak, low, first = [], {}, {}, {}
    for call in trace:
        key = (call["t"], call["wake"])
        if key not in peak:
            order.append(key)
            peak[key], low[key], first[key] = call["context"], call["context"], call["context"]
        peak[key] = max(peak[key], call["context"])
        low[key] = min(low[key], call["context"])
    series = [{"t": t, "day": day(t), "wake": w, "peak": peak[(t, w)], "start": first[(t, w)]} for t, w in order]
    resets = [s["day"] for prev, s in zip(series, series[1:]) if low[(s["t"], s["wake"])] < 0.5 * prev["peak"]]
    return series, resets


def memory_series(log_path):
    entries, chars, points = {}, 0, []
    for line in log_path.read_text().splitlines():
        e = json.loads(line)
        if e["result"].startswith("refused"):
            continue
        if e["op"] == "add_entry":
            entries[e["result"].split()[-1]] = e["args"]["text"]
        elif e["op"] == "update_entry":
            entries[e["args"]["id"]] = e["args"]["text"]
        else:
            entries.pop(e["args"]["id"], None)
        points.append({"day": day(e["when"]), "entries": len(entries), "chars": sum(map(len, entries.values()))})
    return points


def main():
    runs = {a: json.loads((RESULTS / f"northstar_full_30_day_{a}.json").read_text()) for a in ("safe", "baseline")}
    data = {"agents": {}, "incidents": []}
    for a, run in runs.items():
        series, resets = peaks(run["trace"])
        data["agents"][a] = {"totals": run["totals"], "series": series, "resets": resets if a == "baseline" else []}
    pages = {a: {p["page_id"]: p for p in run["pages"]} for a, run in runs.items()}
    for pid, p in pages["safe"].items():
        if p["truth"]["type"] != "incident":
            continue
        inc = p["truth"]["incident_id"]
        data["incidents"].append({
            "incident": inc, "day": int(inc[-2:]), "page": pid, "when": p["when"], "what": INCIDENTS[inc],
            "cause": p["truth"]["cause"][0], "decoy": p["truth"]["decoy"][0],
            "safe": {k: pages["safe"][pid][k] for k in ("answer", "result", "queries")},
            "baseline": {k: pages["baseline"][pid][k] for k in ("answer", "result", "queries")},
        })
    data["memory"] = {"series": memory_series(RESULTS / "northstar_full_30_day_safe_memory.jsonl"), "cap": 15,
                      "final": runs["safe"]["carried_forward"]}
    data["kinds"] = {p["page_id"]: ("incident" if p["truth"]["type"] == "incident" else "noise")
                     for p in runs["safe"]["pages"]}
    html = TEMPLATE.read_text().replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
    OUT.write_text(html)
    print(f"wrote {OUT} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
