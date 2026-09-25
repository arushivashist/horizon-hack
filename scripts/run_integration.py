import json
from src.dejavu.demo.scenarios import run_known_pool, run_vendor
results={"known":run_known_pool(),"vendor":run_vendor()}
print(json.dumps(results,indent=2))
assert results["known"]["anchor"]=="INC-184"
assert results["known"]["decision"]=="restore_connection_limit"
assert results["vendor"]["anchor"]=="INC-141"
assert results["vendor"]["needs_nimble"] is True
print("RESULT: core mock-data integration passed")
