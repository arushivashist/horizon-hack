import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.dejavu.demo.pipeline import run_pipeline

pool=run_pipeline("2026-09-04T19:20:00Z",
 {"service":"checkout-api","failure_class":"connection_pool_exhaustion","dependency":None},
 [{"service":"checkout-api","pool_utilization":0.76,"queue_depth":33,"p99_ms":470}],True)
vendor=run_pipeline("2026-09-09T19:20:00Z",
 {"service":"checkout-api","failure_class":"slow_downstream","dependency":"payrail"},
 [{"service":"checkout-api","upstream":"payrail","upstream_timeout":1,"p99_ms":920}],True)
print(json.dumps({"known_pool":pool,"payrail_vendor":vendor},indent=2))
assert pool["anchor"]=="INC-184"
assert pool["decision"]=="restore_connection_limit"
assert vendor["anchor"]=="INC-141"
assert vendor["needs_external"]
