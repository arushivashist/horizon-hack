from .mockdata import load_agent_world
from ..clients.tinybird import TinybirdClient
from ..clients.nimble import NimbleClient
from ..context.builder import build_context
from ..memory.update_engine import MemoryUpdateEngine

def incident_memory(event):
    p=event["payload"]
    symptoms=p.get("symptoms",[])
    fc="connection_pool_exhaustion" if "CONNECTION_POOL_TIMEOUT" in symptoms else ("slow_downstream" if "UPSTREAM_TIMEOUT" in symptoms else "unknown")
    dep="payrail" if "payrail" in str(p).lower() else None
    return {"id":p["ticket_id"],"kind":"incident","service":event["service"],"failure_class":fc,"dependency":dep,"status":"active","confidence":1.0,"payload":p}

def run_pipeline(now,situation,live_events,use_sponsors=True):
    world=load_agent_world(now)
    engine=MemoryUpdateEngine([incident_memory(x) for x in world["jira_incidents.jsonl"]])
    sponsor={}
    try:
        tb=TinybirdClient()
        sponsor["tinybird"]="configured" if tb.token else "no-key"
    except Exception:
        sponsor["tinybird"]="error"
    context=build_context(engine.active(),situation,max_tokens=1200)
    anchor=context["memories"][0] if context["memories"] else None
    needs_external=not anchor or situation.get("dependency")=="payrail"
    try:
        nimble=NimbleClient()
        sponsor["nimble"]="configured" if nimble.api_key else "no-key"
    except Exception:
        sponsor["nimble"]="error"
    decision="investigate"
    if anchor and situation["failure_class"]=="connection_pool_exhaustion":
        decision="restore_connection_limit"
    elif situation.get("dependency")=="payrail":
        decision="external_revalidation"
    return {"now":now,"sponsors":sponsor,"memory_count":len(engine.active()),"anchor":anchor["id"] if anchor else None,"context_tokens":context["tokens_used"],"context_budget":context["max_tokens"],"needs_external":needs_external,"decision":decision}
