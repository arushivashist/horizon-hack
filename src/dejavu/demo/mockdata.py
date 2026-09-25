import json, urllib.request
BASE="https://raw.githubusercontent.com/Cioran123/wallymartdata/main/mockworld/generated/full_30_day"
def text(name):
    with urllib.request.urlopen(f"{BASE}/{name}",timeout=30) as r: return r.read().decode()
def jsonl(name): return [json.loads(x) for x in text(name).splitlines() if x.strip()]
def visible(records,now): return [x for x in records if x["visible_at"]<=now]
def load_agent_world(now):
    names=["alerts.jsonl","config_changes.jsonl","deployments.jsonl","jira_incidents.jsonl","runbooks.jsonl"]
    return {name:visible(jsonl(name),now) for name in names}
