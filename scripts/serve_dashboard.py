import json, os, webbrowser, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.dejavu.clients.tinybird import TinybirdClient
ROOT=Path(__file__).resolve().parents[1]
SQL="""SELECT run_id, simulated_at, scenario, total_memories, context_tokens, context_budget, created_at FROM dejavu_agent_runs ORDER BY parseDateTimeBestEffortOrNull(simulated_at), parseDateTimeBestEffortOrNull(created_at)"""
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/","/index.html"):
            body=(ROOT/"dashboard/context-window.svg.html").read_bytes(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
        elif self.path=="/api/dashboard":
            try:
                body=json.dumps(TinybirdClient().rows(SQL)).encode(); self.send_response(200); self.send_header("Content-Type","application/json")
            except Exception as e:
                body=json.dumps({"error":str(e)}).encode(); self.send_response(500); self.send_header("Content-Type","application/json")
        else:
            body=b"not found"; self.send_response(404); self.send_header("Content-Type","text/plain")
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
if __name__=="__main__":
    port=int(os.getenv("PORT","8088")); print(f"DejaVu dashboard: http://127.0.0.1:{port}"); ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()
