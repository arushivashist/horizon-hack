import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.dejavu.demo.mockdata import load_agent_world
from src.dejavu.clients.tinybird import TinybirdClient

# Each snapshot is stored under its scenario label. The agent still enforces visible_at <= simulated now.
SCENARIOS=[("day04","2026-09-04T19:20:00Z"),("day09","2026-09-09T19:20:00Z"),("day22","2026-09-22T19:20:00Z"),("day24","2026-09-24T19:20:00Z")]
client=TinybirdClient()

def normalize(event,scenario):
    return {"event_id":event.get("event_id",""),"event_type":event.get("event_type",""),
      "service":event.get("service",""),"timestamp":event.get("timestamp",""),
      "visible_at":event.get("visible_at",""),"scenario":scenario,
      "payload":json.dumps(event.get("payload",{}),separators=(",",":"))}

for scenario,now in SCENARIOS:
    world=load_agent_world(now)
    telemetry=[]
    for source in ("alerts.jsonl","config_changes.jsonl","deployments.jsonl"):
        telemetry.extend(normalize(x,scenario) for x in world[source])
    for table,rows in (
      ("dejavu_telemetry",telemetry),
      ("dejavu_incidents",[normalize(x,scenario) for x in world["jira_incidents.jsonl"]]),
      ("dejavu_runbooks",[normalize(x,scenario) for x in world["runbooks.jsonl"]])):
        # RawTree snapshots may be re-ingested in CI; reads below use event_id de-duplication.
        result=client.ingest_events(table,rows)
        print(table,scenario,result)

for table in ("dejavu_telemetry","dejavu_incidents","dejavu_runbooks"):
    result=client.query(f"SELECT scenario, uniqExact(event_id) AS unique_rows FROM {table} GROUP BY scenario ORDER BY scenario")
    print("VERIFY",table,result.get("data",result))
print("RawTree mock-data ingestion complete")
