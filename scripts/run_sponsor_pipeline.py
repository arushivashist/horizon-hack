import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.dejavu.demo.pipeline import run_pipeline

cases=[
 ("day04","2026-09-04T19:20:00Z",{"service":"checkout-api","failure_class":"connection_pool_exhaustion","dependency":None}),
 ("day09","2026-09-09T19:20:00Z",{"service":"checkout-api","failure_class":"slow_downstream","dependency":"payrail"}),
 ("day22","2026-09-22T19:20:00Z",{"service":"checkout-api","failure_class":"connection_pool_exhaustion","dependency":None}),
 ("day24","2026-09-24T19:20:00Z",{"service":"checkout-api","failure_class":"connection_pool_exhaustion","dependency":None}),
]
results=[run_pipeline(now,s,None,True,name) for name,now,s in cases]
print(json.dumps(results,indent=2))
