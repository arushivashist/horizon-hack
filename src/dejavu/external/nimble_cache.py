from datetime import datetime,timedelta,timezone
def needs_revalidation(ts,ttl=3600):
 if not ts:return True
 return datetime.now(timezone.utc)>=datetime.fromisoformat(ts.replace('Z','+00:00'))+timedelta(seconds=ttl)
