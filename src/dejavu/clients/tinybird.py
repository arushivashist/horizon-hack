import json, os, urllib.parse, urllib.request
class TinybirdClient:
    def __init__(self,token=None,host=None):
        self.token=token or os.getenv("TINYBIRD_TOKEN")
        self.host=(host or os.getenv("TINYBIRD_URL") or os.getenv("TINYBIRD_HOST") or "https://api.tinybird.co").rstrip("/")
    def _request(self,url,data=None,method=None):
        req=urllib.request.Request(url,data=data,method=method,headers={"Authorization":f"Bearer {self.token}","Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=20) as r: return r.read().decode()
    def ingest_events(self,datasource,events):
        body="\n".join(json.dumps(x,separators=(",",":")) for x in events).encode()
        return self._request(f"{self.host}/v0/events?name={urllib.parse.quote(datasource)}",body,"POST")
    def query(self,sql):
        q=urllib.parse.urlencode({"q":sql}); return json.loads(self._request(f"{self.host}/v0/sql?{q}"))
