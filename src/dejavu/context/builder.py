EXCLUDED={'superseded','invalidated','archived'}
def build_context(memories,token_count,max_tokens=6000):
 out=[];used=0
 for m in memories:
  if m.get('status') in EXCLUDED:continue
  n=token_count(m)
  if used+n<=max_tokens:out.append(m);used+=n
 return out
