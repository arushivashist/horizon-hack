from .mockdata import load_agent_world
from ..context.builder import build_context
def _incident_memory(event):
    p=event["payload"]; symptoms=p.get("symptoms",[])
    fc="connection_pool_exhaustion" if "CONNECTION_POOL_TIMEOUT" in symptoms else ("slow_downstream" if "UPSTREAM_TIMEOUT" in symptoms else "unknown")
    dep="payrail" if "payrail" in str(p).lower() else None
    return {"id":p["ticket_id"],"kind":"incident","service":event["service"],"failure_class":fc,"dependency":dep,"status":"active","confidence":1.0,"payload":p}
def run_known_pool():
    now="2026-09-04T19:20:00Z"; world=load_agent_world(now); memories=[_incident_memory(x) for x in world["jira_incidents.jsonl"]]
    context=build_context(memories,{"service":"checkout-api","failure_class":"connection_pool_exhaustion","dependency":None},1200)
    anchor=next((m for m in context["memories"] if m["id"]=="INC-184"),None)
    return {"scenario":"known_pool","now":now,"anchor":anchor["id"] if anchor else None,"decision":"restore_connection_limit" if anchor else "investigate","context_tokens":context["tokens_used"]}
def run_vendor():
    now="2026-09-09T19:20:00Z"; world=load_agent_world(now); memories=[_incident_memory(x) for x in world["jira_incidents.jsonl"]]
    context=build_context(memories,{"service":"checkout-api","failure_class":"slow_downstream","dependency":"payrail"},1200)
    anchor=next((m for m in context["memories"] if m["id"]=="INC-141"),None)
    return {"scenario":"payrail_vendor","now":now,"anchor":anchor["id"] if anchor else None,"decision":"external_revalidation" if anchor else "investigate","needs_nimble":True,"context_tokens":context["tokens_used"]}
if __name__=="__main__":
    import json; print(json.dumps({"known":run_known_pool(),"vendor":run_vendor()},indent=2))
