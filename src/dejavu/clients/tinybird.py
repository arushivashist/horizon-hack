class TinybirdClient:
 async def ingest_telemetry(self,event): raise NotImplementedError
 async def append_memory_event(self,event): raise NotImplementedError
 async def query_active_memory(self,filters,limit=50): raise NotImplementedError
