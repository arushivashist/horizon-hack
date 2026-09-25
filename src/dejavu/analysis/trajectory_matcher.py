from math import sqrt
def cosine_similarity(a,b):
 if not a or len(a)!=len(b):return 0.0
 d=sum(x*y for x,y in zip(a,b)); na=sqrt(sum(x*x for x in a)); nb=sqrt(sum(y*y for y in b))
 return d/(na*nb) if na and nb else 0.0
