"""Minimal local HTTP listener to inspect webhook payloads during testing.

Usage:
    python3 scripts/webhook_receiver.py [port]   # default port 8080

Prints every POSTed JSON body to stdout, pretty-printed, with a timestamp.
Point config.yml's webhook.url at http://<this-machine-IP>:<port>/ingest.
"""
import sys
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        ts = datetime.now().strftime("%H:%M:%S")
        try:
            payload = json.loads(body)
            print(f"\n[{ts}] POST {self.path}")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            print(f"\n[{ts}] POST {self.path} (non-JSON body): {body!r}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, fmt, *args):
        pass  # silence default per-request access log; we print payloads ourselves


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Listening for webhook POSTs on http://0.0.0.0:{port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
