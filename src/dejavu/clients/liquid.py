import json, os, urllib.request
CLASSES=["connection_pool_exhaustion","retry_amplification","slow_downstream","memory_pressure","api_contract_change","unknown"]
class LiquidClient:
    def __init__(self,api_key=None,model=None):
        self.api_key=api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("LIQUID_API_KEY")
        self.model=model or os.getenv("LIQUID_MODEL","liquid/lfm-2.5-1.2b-instruct:free")
    def classify_windows(self,windows):
        if not self.api_key: return {"class":"unknown","confidence":0.0,"mode":"no-key"}
        prompt=f"Classify telemetry as exactly one of {CLASSES}. Return JSON with class, confidence, evidence. Telemetry: {json.dumps(windows)}"
        body=json.dumps({"model":self.model,"messages":[{"role":"user","content":prompt}],"response_format":{"type":"json_object"}}).encode()
        req=urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",data=body,headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=30) as r: data=json.load(r)
        result=json.loads(data["choices"][0]["message"]["content"]); result["mode"]="openrouter"; return result
