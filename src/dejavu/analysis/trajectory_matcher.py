from math import sqrt
def cosine_similarity(a,b):
    if not a or len(a)!=len(b): return 0.0
    dot=sum(x*y for x,y in zip(a,b)); na=sqrt(sum(x*x for x in a)); nb=sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na and nb else 0.0
def slope(values): return 0.0 if len(values)<2 else (values[-1]-values[0])/(len(values)-1)
def trajectory_vector(series,keys):
    out=[]
    for key in keys:
        vals=[float(x) for x in series.get(key,[])]
        if not vals: out += [0.0,0.0]; continue
        scale=max(max(abs(x) for x in vals),1e-9); out += [vals[-1]/scale,slope(vals)/scale]
    return out
def match(current,candidates,keys):
    q=trajectory_vector(current,keys)
    ranked=[{"id":c["id"],"similarity":cosine_similarity(q,trajectory_vector(c["trajectory"],keys))} for c in candidates]
    return sorted(ranked,key=lambda x:x["similarity"],reverse=True)
