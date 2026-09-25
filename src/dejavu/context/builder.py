import json
EXCLUDED={"superseded","invalidated","archived"}
def approximate_tokens(value): return max(1,len(json.dumps(value,sort_keys=True))//4)
def relevance(memory,situation):
    score=0.0
    if memory.get("service")==situation.get("service"): score+=0.35
    if memory.get("failure_class")==situation.get("failure_class"): score+=0.35
    if situation.get("dependency") and memory.get("dependency")==situation.get("dependency"): score+=0.20
    return score+0.10*float(memory.get("confidence",0))
def build_context(memories,situation=None,max_tokens=6000):
    candidates=[m for m in memories if m.get("status","active") not in EXCLUDED]
    if situation: candidates=sorted(candidates,key=lambda m:relevance(m,situation),reverse=True)
    out=[]; used=0
    for m in candidates:
        n=approximate_tokens(m)
        if used+n<=max_tokens: out.append(m); used+=n
    return {"memories":out,"tokens_used":used,"max_tokens":max_tokens}
