import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dejavu.clients.tinybird import TinybirdClient

ROOT = Path(__file__).resolve().parents[1]

RUNS_SQL = """
SELECT run_id, simulated_at, scenario, total_memories, context_tokens, context_budget, created_at
FROM dejavu_agent_runs
ORDER BY parseDateTimeBestEffortOrNull(simulated_at), parseDateTimeBestEffortOrNull(created_at)
"""

MEMORIES_SQL = """
SELECT memory_id, memory_json, scenario, simulated_at, created_at
FROM dejavu_memories
ORDER BY parseDateTimeBestEffortOrNull(simulated_at), parseDateTimeBestEffortOrNull(created_at)
"""

MUTATIONS_SQL = """
SELECT mutation_id, operation, target_id, reason, evidence_ids, scenario, simulated_at, created_at
FROM dejavu_memory_events
ORDER BY parseDateTimeBestEffortOrNull(simulated_at), parseDateTimeBestEffortOrNull(created_at)
"""

def dashboard_rows(rows):
    """Keep only the latest recorded run for each demo scenario."""
    latest = {}
    for row in rows:
        scenario = row.get("scenario")
        if not scenario:
            continue
        current = latest.get(scenario)
        stamp = (row.get("created_at") or "", row.get("run_id") or "")
        current_stamp = (
            (current or {}).get("created_at") or "",
            (current or {}).get("run_id") or "",
        )
        if current is None or stamp >= current_stamp:
            latest[scenario] = row
    return sorted(
        latest.values(),
        key=lambda r: (r.get("simulated_at") or "", r.get("scenario") or ""),
    )

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (ROOT / "docs/experiment-dashboard.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/api/dashboard":
            try:
                rows = TinybirdClient().rows(SQL)
                body = json.dumps(dashboard_rows(rows)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            except Exception as e:
                body = json.dumps({"error": str(e)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")

        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8088"))
    print(f"DejaVu dashboard: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
