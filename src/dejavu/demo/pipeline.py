import json, os, uuid
from datetime import datetime,timezone
from ..clients.tinybird import TinybirdClient
from ..clients.nimble import NimbleClient
from ..context.builder import build_context
from ..memory.update_engine import MemoryUpdateEngine

def incident_memory_row(row):
    p=json.loads(row.get("payload","{}")) if isinstance(row.get("payload"),str) else row.get("payload",{})
    symptoms=p.get("symptoms",[])
    fc="connection_pool_exhaustion" if "CONNECTION_POOL_TIMEOUT" in symptoms else ("slow_downstream" if "UPSTREAM_TIMEOUT" in symptoms else "unknown")
    dep="payrail" if "payrail" in str(p).lower() else None
    return {"id":p.get("ticket_id",row.get("event_id","unknown")),"kind":"incident","service":row.get("service",""),"failure_class":fc,"dependency":dep,"status":"active","confidence":1.0,"payload":p}

def run_pipeline(now,situation,live_events=None,use_sponsors=True,scenario="demo"):
    tb=TinybirdClient()
    safe_now=now.replace("'","")
    incident_rows=tb.rows(f"SELECT event_id,event_type,service,timestamp,visible_at,scenario,payload FROM dejavu_incidents WHERE parseDateTimeBestEffortOrNull(visible_at) <= parseDateTimeBestEffort('{safe_now}') ORDER BY parseDateTimeBestEffortOrNull(visible_at)")
    memories=[incident_memory_row(x) for x in incident_rows]
    engine=MemoryUpdateEngine(memories)
    budget=int(os.getenv("MAX_MEMORY_CONTEXT_TOKENS","1200"))
    context=build_context(engine.active(),situation,max_tokens=budget)
    anchor=context["memories"][0] if context["memories"] else None
    needs_external=not anchor or situation.get("dependency")=="payrail"
    decision="investigate"
    if anchor and situation["failure_class"]=="connection_pool_exhaustion": decision="restore_connection_limit"
    elif situation.get("dependency")=="payrail": decision="external_revalidation"

    operation="ADD"
    target=f"lesson-{scenario}-{now[:10]}"
    record={"id":target,"kind":"lesson","service":situation.get("service",""),"failure_class":situation.get("failure_class"),"dependency":situation.get("dependency"),"status":"active","confidence":0.8,"payload":{"decision":decision}}
    if anchor:
        operation="REVALIDATE"; target=anchor["id"]; record=anchor
    mutation=engine.apply(operation,record,"Outcome from DejaVu run",[anchor["id"]] if anchor else [])

    run_id=f"{scenario}-{uuid.uuid4().hex[:10]}"
    created=datetime.now(timezone.utc).isoformat()
    tb.ingest_events("dejavu_memory_events",[{"run_id":run_id,"simulated_at":now,"scenario":scenario,"operation":mutation["operation"],"target_id":mutation["targetId"],"reason":mutation["reason"],"evidence_ids":json.dumps(mutation["evidenceIds"]),"created_at":created}])
    tb.ingest_events("dejavu_agent_runs",[{"run_id":run_id,"simulated_at":now,"scenario":scenario,"service":situation.get("service",""),"failure_class":situation.get("failure_class",""),"total_memories":len(engine.records),"active_memories":len(engine.active()),"retrieved_memories":len(context["memories"]),"context_tokens":context["tokens_used"],"context_budget":context["max_tokens"],"anchor":anchor["id"] if anchor else "","needs_external":1 if needs_external else 0,"decision":decision,"created_at":created}])
    return {"run_id":run_id,"now":now,"memory_count":len(engine.active()),"anchor":anchor["id"] if anchor else None,"context_tokens":context["tokens_used"],"context_budget":context["max_tokens"],"needs_external":needs_external,"decision":decision,"memory_operation":mutation["operation"]}
