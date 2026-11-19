"""
The plugin's web server. What Farmhand asks it for, and what its page asks it for:

    GET  /manifest             farmhand-plugin.json
    GET  /health               2xx while well; else a short reason, shown on Farmhand's Plugins page
    GET  /                     the page, shown inside Farmhand at /plugins/prusa-connect/
    GET  /api/status           the reporter's snapshot (reporter.py), as JSON
    POST /api/address          {"url": "http://192.168.10.93:8080"}: where Prusa Connect is (a new one needs pairing again)
    POST /api/pairing          start pairing: a short code to approve on Prusa Connect's page
    POST /api/pairing/check    {state: paired | pending | denied | expired | none, message}
    POST /api/link             {"printer_id": 3, "device_id": "<Prusa Connect's id>" | null}: which printer is which

The page uses relative addresses ("api/status"), so they work inside Farmhand and on the plugin's own port alike.
"""
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Settings
from .connect import ConnectError
from .reporter import Reporter

PAGE = Path(__file__).with_name("page.html")
MANIFESTS = [Path("/farmhand-plugin.json"), Path(__file__).resolve().parent.parent / "farmhand-plugin.json"]
MAX_BODY = 64 * 1024


def read_manifest() -> dict:
    for path in MANIFESTS:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("farmhand-plugin.json is missing")


class Handler(BaseHTTPRequestHandler):
    reporter: Reporter
    settings: Settings
    manifest: dict

    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/manifest":
            return self.send_json(self.manifest)
        if path == "/health":
            return self.health()
        if path in ("/", "/index.html"):
            return self.send_body(PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/status":
            return self.send_json(self.reporter.snapshot())
        self.send_json({"detail": "There's nothing here."}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self.read_json()
            if path == "/api/address":
                self.settings.set_address(body.get("url"))
                answer = self.reporter.snapshot()
            elif path == "/api/pairing":
                answer = self.reporter.connect.start_pairing()
            elif path == "/api/pairing/check":
                answer = self.reporter.connect.check_pairing()
            elif path == "/api/link":
                self.settings.link(body.get("printer_id"), body.get("device_id"))
                answer = self.reporter.snapshot()
            else:
                return self.send_json({"detail": "There's nothing here."}, HTTPStatus.NOT_FOUND)
        except ValueError as e:  # bad JSON, a bad address or link
            return self.send_json({"detail": str(e)}, HTTPStatus.BAD_REQUEST)
        except ConnectError as e:
            return self.send_json({"detail": e.message, "kind": e.kind}, HTTPStatus.BAD_GATEWAY)
        self.reporter.wake()
        self.send_json(answer)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("That's too much to send.")
        body = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object.")
        return body

    def health(self):
        """Unwell only when Farmhand refuses the plugin (its token, a permission): the operator fixes that on the
        Plugins page, which shows this answer. Prusa Connect being down is shown on the plugin's page and the printers'."""
        problem = self.reporter.problem()
        if problem and problem.kind in ("setup", "refused", "forbidden"):
            return self.send_body(problem.short.encode("utf-8"), "text/plain; charset=utf-8", HTTPStatus.SERVICE_UNAVAILABLE)
        self.send_body(b"ok", "text/plain; charset=utf-8")

    def send_json(self, value, status=HTTPStatus.OK):
        self.send_body(json.dumps(value).encode("utf-8"), "application/json", status)

    def send_body(self, body: bytes, content_type: str, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # quiet: Farmhand asks /health every 30 s


def make_server(port: int, reporter: Reporter, settings: Settings, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    handler = type("PrusaConnectHandler", (Handler,), {"reporter": reporter, "settings": settings, "manifest": read_manifest()})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
