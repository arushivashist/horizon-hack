import json, os, urllib.request
class NimbleClient:
    def __init__(self,api_key=None,base_url=None):
        self.api_key=api_key or os.getenv("NIMBLE_API_KEY")
        self.base_url=(base_url or os.getenv("NIMBLE_BASE_URL") or "https://api.webit.live").rstrip("/")
    def _post(self,path,payload):
        if not self.api_key: return {"mode":"no-key","results":[]}
        req=urllib.request.Request(self.base_url+path,data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=45) as r: return json.load(r)
    def search(self,query): return self._post("/api/v1/realtime/search",{"query":query})
    def extract(self,url): return self._post("/api/v1/realtime/extract",{"url":url})
