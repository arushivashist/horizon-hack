"""Ingest the already-produced 30-day Claude experiment into RawTree without rerunning the model."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dejavu.clients.tinybird import TinybirdClient

ROOT=Path(__file__).resolve().parents[1]
EXPERIMENT_ID="northstar-30-day-safe-traced"
DATA_PATH=ROOT/"prototype/results/northstar-30-day-safe-traced/dashboard_data.json"
MEMORY_LOG=ROOT/"prototype/results/northstar-30-day-safe-traced/memory_log.jsonl"
client=TinybirdClient()
data=json.loads(DATA_PATH.read_text())
memory_log=[json.loads(x) for x in MEMORY_LOG.read_text().splitlines() if x.strip()]

page_rows=[{
 "record_id":f"{EXPERIMENT_ID}:page:{p['id']}","experiment_id":EXPERIMENT_ID,
 "page_id":p["id"],"day":p["day"],"when_text":p["when"],"incident_id":p.get("incident") or "",
 "monitor":p.get("monitor") or "","service":p.get("service") or "","action":p["memory"]["action"],
 "answer":p["memory"]["answer"],"result":p["memory"]["result"],"queries":p["memory"]["queries"],
 "memory_edits":json.dumps(p.get("edits",[]),separators=(",",":"))
} for p in data["pages"]]

series=[]
for kind,key in (("memory_count","memory"),("memory_context","memory_context"),("naive_context","naive_context")):
    for i,p in enumerate(data.get(key) or []):
        series.append({"record_id":f"{EXPERIMENT_ID}:{kind}:{i}","experiment_id":EXPERIMENT_ID,
          "series":kind,"point_index":i,"day":p["day"],"value":p.get("n",p.get("v",0))})

events=[{"record_id":f"{EXPERIMENT_ID}:memory-event:{i}","experiment_id":EXPERIMENT_ID,
 "event_index":i,"when_text":e.get("when",""),"operation":e.get("op",""),
 "args_json":json.dumps(e.get("args",{}),separators=(",",":")),"result":e.get("result","")}
 for i,e in enumerate(memory_log)]

summary=[{"experiment_id":EXPERIMENT_ID,"pages":data["totals"]["memory"]["pages"],
 "correct":data["totals"]["memory"]["correct"],"queries":data["totals"]["memory"]["queries"],
 "calls":data["totals"]["memory"]["calls"],"max_context":data["totals"]["memory"]["max_context"],
 "cost":data["totals"]["memory"]["cost"],"memory_points":len(data["memory"]),
 "memory_context_points":len(data.get("memory_context") or [])}]

for table,rows in (("dejavu_experiment_pages",page_rows),("dejavu_experiment_series",series),
                   ("dejavu_experiment_memory_events",events),("dejavu_experiments",summary)):
    print(table,client.ingest_events(table,rows))

for label,expected,table in (("pages",len(page_rows),"dejavu_experiment_pages"),
 ("series",len(series),"dejavu_experiment_series"),("memory_events",len(events),"dejavu_experiment_memory_events")):
    rows=client.rows(f"SELECT uniqExact(record_id) AS n FROM {table} WHERE experiment_id = '{EXPERIMENT_ID}'")
    actual=int(rows[0]["n"]) if rows else 0
    if actual != expected: raise SystemExit(f"VERIFY FAILED {label}: expected {expected}, got {actual}")
    print("VERIFY",label,actual)
print("RawTree contains the preserved 30-day Claude experiment; no model rerun performed.")
