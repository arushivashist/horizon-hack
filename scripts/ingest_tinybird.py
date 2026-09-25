import json, os, sys, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.dejavu.demo.mockdata import load_agent_world

TOKEN=os.environ["TINYBIRD_TOKEN"]
HOST=(os.getenv("TINYBIRD_URL") or "https://api.tinybird.co").rstrip("/")
SCENARIOS=[("day04","2026-09-04T19:20:00Z"),("day09","2026-09-09T19:20:00Z")]

def post_events(name, rows):
    if not rows: return
    url=HOST+"/v0/events?"+urllib.parse.urlencode({"name":name,"wait":"true"})
    body="\n".join(json.dumps(r,separators=(",",":")) for r in rows).encode()
    req=urllib.request.Request(url,data=body,method="POST",headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/x-ndjson"})
    with urllib.request.urlopen(req,timeout=30) as resp:
        print(name,resp.status,resp.read().decode()[:300])

def normalize(event,scenario):
    return {"event_id":event.get("event_id",""),"event_type":event.get("event_type",""),"service":event.get("service",""),"timestamp":event.get("timestamp",""),"visible_at":event.get("visible_at",""),"scenario":scenario,"payload":json.dumps(event.get("payload",{}),separators=(",",":"))}

for scenario,now in SCENARIOS:
    world=load_agent_world(now)
    telemetry=[]
    for source in ("alerts.jsonl","config_changes.jsonl","deployments.jsonl"):
        telemetry.extend(normalize(x,scenario) for x in world[source])
    incidents=[normalize(x,scenario) for x in world["jira_incidents.jsonl"]]
    runbooks=[normalize(x,scenario) for x in world["runbooks.jsonl"]]
    post_events("dejavu_telemetry",telemetry)
    post_events("dejavu_incidents",incidents)
    post_events("dejavu_runbooks",runbooks)
print("Tinybird mock-data ingestion complete")
