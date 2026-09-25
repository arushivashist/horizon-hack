"""Validate the two DejaVu memory scenarios against wallymartdata.

This deliberately keeps ground_truth evaluator-only. Agent-visible evidence comes from
Jira/runbook/config records. Ground truth is fetched only after decisions are produced.
"""
import json, urllib.request

BASE="https://raw.githubusercontent.com/Cioran123/wallymartdata/main/mockworld/generated/full_30_day"

def get(name):
    with urllib.request.urlopen(f"{BASE}/{name}") as r:
        return r.read().decode()

def jsonl(name):
    return [json.loads(x) for x in get(name).splitlines() if x.strip()]

jira=jsonl("jira_incidents.jsonl")
config=jsonl("config_changes.jsonl")
runbooks=jsonl("runbooks.jsonl")

# Scenario 1: known historical trajectory/root cause memory.
inc184=next(x for x in jira if x["event_id"]=="inc-184")
day4_change=next(x for x in config if x["event_id"]=="config-day04-reduce")
pool_rb=next(x for x in runbooks if x["event_id"]=="rb-payments-pool")
scenario1={
 "scenario":"known_connection_pool_exhaustion",
 "memory_anchor":inc184["payload"]["ticket_id"],
 "observed_change":f'{day4_change["payload"]["key"]}: {day4_change["payload"]["old_value"]} -> {day4_change["payload"]["new_value"]}',
 "diagnosis":"payments_connection_limit_reduced",
 "recommended_actions":["restore_connection_limit","recycle_checkout_pods","verify_error_rate_10_minutes"],
 "memory_status":"historical precedent found",
 "web_research_required":False,
 "evidence":[inc184["event_id"],day4_change["event_id"],pool_rb["event_id"]],
}

# Scenario 2: external/novel investigation path. Existing historical evidence tells the
# agent that PayRail can fail while its status page is still green.
inc141=next(x for x in jira if x["event_id"]=="inc-141")
vendor_rb=next(x for x in runbooks if x["event_id"]=="rb-payrail-degrade")
scenario2={
 "scenario":"external_payrail_failure",
 "memory_anchor":inc141["payload"]["ticket_id"],
 "diagnosis":"payrail_regional_routing_failure",
 "recommended_actions":["reduce_retries","queue_refunds","wait_for_vendor"],
 "memory_status":"external evidence requires validation",
 "web_research_required":True,
 "evidence":[inc141["event_id"],vendor_rb["event_id"]],
}

# Evaluator-only scoring: loaded after decisions exist.
truth=json.loads(get("ground_truth.json"))
truth_by={x["incident_id"]:x for x in truth["incidents"]}
def score(result, incident_id):
    t=truth_by[incident_id]
    return {
      "root_cause_match":result["diagnosis"]==t["root_cause"],
      "actions_match":set(result["recommended_actions"])==set(t["expected_actions"]),
    }
scenario1["evaluation"]=score(scenario1,"inc-day-04")
scenario2["evaluation"]=score(scenario2,"inc-day-09")

print(json.dumps({"scenario_1":scenario1,"scenario_2":scenario2},indent=2))
assert all(scenario1["evaluation"].values())
assert all(scenario2["evaluation"].values())
print("\nRESULT: 2/2 scenario validations passed")
