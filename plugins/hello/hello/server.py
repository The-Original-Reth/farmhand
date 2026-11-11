"""
The plugin's own web server. What Farmhand asks it for, and what its page asks it for:

    GET  /manifest      farmhand-plugin.json: Farmhand reads it when the operator adds the plugin by its address
    GET  /health        Farmhand asks every 30 s; 2xx while well, else a short reason (shown on the Plugins page)
    GET  /              the page, shown inside Farmhand at /plugins/hello/
    GET  /api/status    the snapshot of the farm (watcher.py), as JSON
    GET  /api/events    server-sent events: the snapshot again each time it changes, so the page updates by itself
    POST /api/settings  {"hidden_printers": [ids]}: which printers the page leaves out

Behind Farmhand the browser asks for /plugins/hello/api/status, and Farmhand passes it on as /api/status. That's why
the page uses relative addresses ("api/status", never "/api/status"): they work both inside Farmhand and when the
plugin is opened straight on its own port.
"""
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Settings
from .watcher import Watcher

PAGE = Path(__file__).with_name("page.html")
# The manifest is at /farmhand-plugin.json in the image; beside this folder when run from a checkout
MANIFESTS = [Path("/farmhand-plugin.json"), Path(__file__).resolve().parent.parent / "farmhand-plugin.json"]
KEEPALIVE_SECONDS = 15.0  # a comment on the page's event stream this often, so proxies keep it open


def read_manifest() -> dict:
    for path in MANIFESTS:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("farmhand-plugin.json is missing")


class Handler(BaseHTTPRequestHandler):
    # Set by make_server()
    watcher: Watcher
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
            return self.send_json(self.watcher.snapshot())
        if path == "/api/events":
            return self.page_events()
        self.send_json({"detail": "There's nothing here."}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/settings":
            return self.send_json({"detail": "There's nothing here."}, HTTPStatus.NOT_FOUND)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            hidden = self.settings.set_hidden_printers(body.get("hidden_printers") if isinstance(body, dict) else None)
        except ValueError as e:  # bad JSON, or not a list of ids
            return self.send_json({"detail": str(e)}, HTTPStatus.BAD_REQUEST)
        self.watcher.settings_changed()
        self.send_json({"hidden_printers": hidden})

    def health(self):
        """
        Well unless Farmhand has refused this plugin (its token, or a permission): that's something the operator must
        fix on Farmhand's Plugins page, which shows this answer. Farmhand being down isn't the plugin being unwell.
        """
        problem = self.watcher.problem()
        if problem and problem.kind in ("setup", "refused", "forbidden"):
            return self.send_body(problem.short.encode("utf-8"), "text/plain; charset=utf-8", HTTPStatus.SERVICE_UNAVAILABLE)
        self.send_body(b"ok", "text/plain; charset=utf-8")

    def page_events(self):
        """The snapshot each time it changes, until the browser goes away (it reconnects by itself)."""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")  # tells nginx-like proxies not to hold events back
        self.send_header("Connection", "close")  # this connection is used for nothing else
        self.end_headers()
        self.close_connection = True
        version = -1
        try:
            while True:
                snapshot = self.watcher.snapshot()
                if snapshot["version"] != version:
                    version = snapshot["version"]
                    self.wfile.write(f"data: {json.dumps(snapshot)}\n\n".encode("utf-8"))
                else:
                    self.wfile.write(b": still here\n\n")
                self.wfile.flush()
                self.watcher.wait_for_change(version, KEEPALIVE_SECONDS)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # the page was closed

    # ------------------------------------------------------------------ helpers

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
        pass  # quiet: Farmhand asks /health every 30 s. Problems are printed by the watcher


def make_server(port: int, watcher: Watcher, settings: Settings, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    handler = type("HelloHandler", (Handler,), {"watcher": watcher, "settings": settings, "manifest": read_manifest()})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True  # open event streams don't stop the plugin from shutting down
    return server
