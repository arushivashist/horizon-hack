import json, os, urllib.request

class TinybirdClient:
    """RawTree-backed analytics client. Class name kept for compatibility."""
    def __init__(self, token=None, host=None):
        self.token=token or os.getenv("RAWTREE_API_KEY") or os.getenv("TINYBIRD_TOKEN")
        self.host=(host or os.getenv("RAWTREE_URL") or "https://api.rawtree.com").rstrip("/")

    def _request(self,path,data=None,method=None):
        body=None if data is None else json.dumps(data).encode()
        req=urllib.request.Request(self.host+path,data=body,method=method,
            headers={"Authorization":f"Bearer {self.token}","Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read().decode()
            return json.loads(raw) if raw else {}

    def ingest_events(self,table,events):
        if not events: return {"inserted":0}
        return self._request(f"/v1/tables/{table}",events,"POST")

    def query(self,sql):
        return self._request("/v1/query",{"sql":sql,"format":"JSON"},"POST")
