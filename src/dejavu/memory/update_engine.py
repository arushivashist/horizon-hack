from datetime import datetime,timezone
class MemoryUpdateEngine:
    def __init__(self,records=None):
        self.records={r["id"]:dict(r) for r in (records or [])}; self.events=[]
    def apply(self,operation,record,reason,evidence_ids=None):
        now=datetime.now(timezone.utc).isoformat(); rid=record["id"]; old=self.records.get(rid)
        if operation=="ADD": self.records[rid]={**record,"status":record.get("status","active")}
        elif operation=="REVALIDATE" and old: self.records[rid]={**old,"lastValidatedAt":now,"status":"active"}
        elif operation in {"SUPERSEDE","INVALIDATE","ARCHIVE"} and old: self.records[rid]={**old,"status":operation.lower()}
        else: raise ValueError(f"invalid mutation {operation} for {rid}")
        event={"operation":operation,"targetId":rid,"reason":reason,"evidenceIds":evidence_ids or [],"createdAt":now}
        self.events.append(event); return event
    def active(self): return [x for x in self.records.values() if x.get("status","active")=="active"]
