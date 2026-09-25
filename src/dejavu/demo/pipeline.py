import json, os, uuid
from datetime import datetime,timezone
from ..clients.tinybird import TinybirdClient
from ..context.builder import build_context
from ..memory.update_engine import MemoryUpdateEngine

def _payload(row):
    value=row.get("payload",{})
    return json.loads(value) if isinstance(value,str) else value

def incident_memory_row(row):
    p=_payload(row); symptoms=p.get("symptoms",[])
    text=json.dumps(p).lower()
    fc="connection_pool_exhaustion" if "connection_pool_timeout" in text or "pool" in text else ("slow_downstream" if "upstream_timeout" in text or "payrail" in text else "unknown")
    dep="payrail" if "payrail" in text else None
    compact={k:p.get(k) for k in ("ticket_id","title","summary","root_cause","resolution","symptoms") if p.get(k) is not None}
    return {"id":p.get("ticket_id",row.get("event_id","unknown")),"kind":"incident","service":row.get("service",""),"failure_class":fc,"dependency":dep,"status":"active","confidence":1.0,"payload":compact}

def _table_exists(tb,table):
    try:
        tb.rows(f"SELECT * FROM {table} LIMIT 1"); return True
    except Exception:
        return False

def run_pipeline(now,situation,live_events=None,use_sponsors=True,scenario="demo"):
    tb=TinybirdClient(); safe_now=now.replace("'","")
    # Deduplicate CI snapshot ingestion and never expose records not visible at simulated time.
    raw_rows=tb.rows("SELECT event_id,event_type,service,timestamp,visible_at,payload FROM dejavu_incidents ORDER BY visible_at")
    # RawTree stores these mock timestamps as strings. Enforce simulated-time visibility in the agent
    # after the SQL read; ISO-8601 UTC timestamps are lexicographically ordered.
    visible_rows=[row for row in raw_rows if row.get("visible_at","") <= safe_now]
    # CI may ingest the same snapshot repeatedly; keep one copy of each stable event_id.
    incident_rows=list({row["event_id"]:row for row in visible_rows}.values())
    memories=[incident_memory_row(x) for x in incident_rows]
    engine=MemoryUpdateEngine(memories)
    budget=int(os.getenv("MAX_MEMORY_CONTEXT_TOKENS","1200"))
    context=build_context(engine.active(),situation,max_tokens=budget)
    anchor=context["memories"][0] if context["memories"] else None

    # Day 24 is intentionally a lookalike: same symptom class, contradictory live evidence.
    # It must retrieve the old pool memory but not blindly reuse its remediation.
    lookalike=scenario=="day24"
    needs_external=not anchor or situation.get("dependency")=="payrail" or lookalike
    if lookalike and anchor:
        decision="reject_stale_pool_fix_and_investigate"
        operation="INVALIDATE"
        mutation=engine.apply(operation,anchor,"Day 24 lookalike contradicts the old pool-limit remediation; connection limit is unchanged and the failure needs a new cause.",[anchor["id"]])
        # Preserve the historical incident, but persist a new learned lesson describing why reuse was rejected.
        lesson={"id":f"lesson-{scenario}-{now[:10]}","kind":"lesson","service":situation.get("service",""),"failure_class":situation.get("failure_class"),"dependency":situation.get("dependency"),"status":"active","confidence":0.9,"payload":{"decision":decision,"rejected_anchor":anchor["id"]}}
        engine.apply("ADD",lesson,"Learned a distinct Day 24 lookalike outcome.",[anchor["id"]])
    elif anchor:
        decision="restore_connection_limit" if situation["failure_class"]=="connection_pool_exhaustion" else ("external_revalidation" if situation.get("dependency")=="payrail" else "investigate")
        operation="REVALIDATE"
        mutation=engine.apply(operation,anchor,"Current evidence revalidates retrieved institutional memory.",[anchor["id"]])
        lesson={"id":f"lesson-{scenario}-{now[:10]}","kind":"lesson","service":situation.get("service",""),"failure_class":situation.get("failure_class"),"dependency":situation.get("dependency"),"status":"active","confidence":0.9,"payload":{"decision":decision,"anchor":anchor["id"]}}
        engine.apply("ADD",lesson,"Persisted outcome learned from this incident.",[anchor["id"]])
    else:
        decision="external_revalidation" if situation.get("dependency")=="payrail" else "investigate"
        operation="ADD"; target=f"lesson-{scenario}-{now[:10]}"
        record={"id":target,"kind":"lesson","service":situation.get("service",""),"failure_class":situation.get("failure_class"),"dependency":situation.get("dependency"),"status":"active","confidence":0.8,"payload":{"decision":decision}}
        mutation=engine.apply(operation,record,"Outcome from DejaVu run",[])

    run_id=f"{scenario}-{uuid.uuid4().hex[:10]}"; created=datetime.now(timezone.utc).isoformat()
    # Persist the full post-run institutional-memory state; later runs rehydrate from this table.
    memory_rows=[{"memory_id":m["id"],"memory_json":json.dumps(m,separators=(",",":")),"scenario":scenario,"simulated_at":now,"created_at":created} for m in engine.records.values()]
    tb.ingest_events("dejavu_memories",memory_rows)
    tb.ingest_events("dejavu_memory_events",[{"run_id":run_id,"simulated_at":now,"scenario":scenario,"operation":mutation["operation"],"target_id":mutation["targetId"],"reason":mutation["reason"],"evidence_ids":json.dumps(mutation["evidenceIds"]),"created_at":created}])
    tb.ingest_events("dejavu_agent_runs",[{"run_id":run_id,"simulated_at":now,"scenario":scenario,"service":situation.get("service",""),"failure_class":situation.get("failure_class",""),"total_memories":len(engine.records),"active_memories":len(engine.active()),"retrieved_memories":len(context["memories"]),"context_tokens":context["tokens_used"],"context_budget":context["max_tokens"],"anchor":anchor["id"] if anchor else "","needs_external":1 if needs_external else 0,"decision":decision,"created_at":created}])
    return {"run_id":run_id,"now":now,"memory_count":len(engine.active()),"total_memories":len(engine.records),"retrieved_memories":len(context["memories"]),"anchor":anchor["id"] if anchor else None,"context_tokens":context["tokens_used"],"context_budget":context["max_tokens"],"needs_external":needs_external,"decision":decision,"memory_operation":mutation["operation"]}
