from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json

HOST = "127.0.0.1"
PORT = 8765

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CYVANTA Local Demo Lab</title>
<style>
body{margin:0;background:#0b1020;color:#edf2ff;font:16px/1.6 Segoe UI,Arial,sans-serif}
main{max-width:760px;margin:8vh auto;padding:32px;background:#151d33;border:1px solid #34415f;border-radius:18px}
small{color:#77e5ef;letter-spacing:.14em}h1{margin:.4em 0;color:#fff}p{color:#bdc9e5}
.tag{display:inline-block;padding:6px 12px;border-radius:999px;background:#173d3c;color:#8ff0d2}
code{color:#8fe8f0}
</style>
</head>
<body><main>
<small>CYVANTA / CONTROLLED TEST ENVIRONMENT</small>
<h1>Local Demo Lab</h1>
<p class="tag">LOOPBACK ONLY | 127.0.0.1</p>
<p>This harmless demonstration application is running on this computer for CYVANTA workflow validation.</p>
<p>It contains no scanning, exploitation, credential collection, or remote-control functionality.</p>
<p>Health endpoint: <code>/health</code></p>
<p>Environment: <code>local-demo</code></p>
</main></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({
                "status": "ok",
                "service": "CYVANTA Local Demo Lab",
                "environment": "local-demo",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        elif self.path == "/" or self.path == "/index.html":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            body = b'{"detail":"Not found"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("[demo-lab] " + (fmt % args))

if __name__ == "__main__":
    print(f"CYVANTA Demo Lab listening only on http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop. This server is not exposed to your network.")
    HTTPServer((HOST, PORT), Handler).serve_forever()
