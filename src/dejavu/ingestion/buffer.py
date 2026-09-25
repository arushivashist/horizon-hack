import asyncio
class TelemetryBuffer:
 def __init__(self):self.queue=asyncio.Queue(maxsize=1000)
 async def put(self,e):await self.queue.put(e)
 async def get(self):return await self.queue.get()
