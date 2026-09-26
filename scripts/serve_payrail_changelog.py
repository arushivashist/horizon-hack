#!/usr/bin/env python3
"""Controlled public PayRail changelog for the Nimble memory-validity demo."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHANGELOG = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>PayRail Developer Changelog</title></head>
<body>
<main>
<h1>PayRail Developer Changelog</h1>
<article>
  <h2>2026-10-05 · Regional failover guidance</h2>
  <p>Regional failover is now supported. During sustained US West routing failures,
  merchants should route traffic to the backup region. Previous wait-for-recovery
  guidance is deprecated.</p>
  <p>Recommended handling: reduce retry pressure, route traffic to the backup region,
  and verify payment success after failover.</p>
</article>
<article>
  <h2>2026-09-06 · Idempotency key documentation</h2>
  <p>Documented the idempotency key header. No breaking change.</p>
</article>
</main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/changelog":
            body = CHANGELOG.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/health":
            body = b'{"status":"ok","service":"payrail-docs"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8091)
    args = p.parse_args()
    print(f"PayRail changelog: http://127.0.0.1:{args.port}/changelog")
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
