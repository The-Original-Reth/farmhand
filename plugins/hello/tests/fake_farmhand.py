"""
A stand-in for Farmhand's plugin API (/plugin-api/v1), answering in exactly its shapes (docs/plugins.md): the token
checked, permissions checked, 429 on demand, and /events that the test pushes events into.
"""
from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "good-token"
EVERYTHING = {"printers:read", "prints:read", "farm:read"}


class FakeFarmhand:
    def __init__(self, port: int = 0):
        self.printers = [
            {"id": 1, "name": "VT 1190", "kind": "Voron Trident", "connection_type": "moonraker", "addresses": {}},
            {"id": 2, "name": "Core One", "kind": None, "connection_type": "prusalink", "addresses": {}},
        ]
        self.prints = {
            1: {"state": "printing", "progress": 42.4, "file": "Frog.gcode", "error": None},
            2: {"state": None, "progress": None, "file": None, "error": None},
        }
        self.permissions = set(EVERYTHING)
        self.busy_for = 0  # the next this-many calls get 429
        self.calls: list[str] = []
        self._listeners: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._sequence = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                fake.calls.append(self.path)
                fake.answer(self)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/plugin-api/v1"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def stop(self):
        with self._lock:
            for q in self._listeners:
                q.put(None)  # ends each event stream
        self.server.shutdown()
        self.server.server_close()

    # ------------------------------------------------------------------ what the test does

    def push(self, kind: str, **data):
        """An event, to everyone listening on /events."""
        with self._lock:
            self._sequence += 1
            event = {"id": self._sequence, "type": kind, "at": "2026-11-11T14:02:11+00:00", **data}
            for q in self._listeners:
                q.put(event)

    def listening(self) -> int:
        with self._lock:
            return len(self._listeners)

    # ------------------------------------------------------------------ the plugin API

    def answer(self, h: BaseHTTPRequestHandler):
        if h.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self.send(h, 401, {"detail": "That plugin token isn't valid: it was replaced by a new one."})
        if self.busy_for > 0:
            self.busy_for -= 1
            return self.send(h, 429, {"detail": "This plugin is asking Farmhand too often."}, {"Retry-After": "1"})
        path = h.path.removeprefix("/plugin-api/v1")
        if path == "/printers":
            return self.allowed(h, "printers:read") and self.send(h, 200, {"printers": self.printers})
        if path.startswith("/printers/") and path.endswith("/print"):
            pid = int(path.split("/")[2])
            if pid not in self.prints:
                return self.send(h, 404, {"detail": "Printer not found"})
            return self.allowed(h, "prints:read") and self.send(h, 200, self.prints[pid])
        if path == "/farm":
            return self.allowed(h, "farm:read") and self.send(h, 200, {
                "scheme": "farmhand", "mode": "dark", "time_zone": "Europe/London",
                "colors": {"bg": "#1B1D1E", "amber": "#E39F3A"},
            })
        if path == "/events":
            return self.allowed(h, "prints:read") and self.events(h)
        self.send(h, 404, {"detail": "Not Found"})

    def allowed(self, h, permission: str) -> bool:
        if permission in self.permissions:
            return True
        self.send(h, 403, {"detail": f"The \"hello\" plugin hasn't been given the {permission} permission, which this needs."})
        return False

    def send(self, h, status: int, body: dict, headers: dict | None = None) -> bool:
        data = json.dumps(body).encode()
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(data)
        return True

    def events(self, h):
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._listeners.append(q)
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Connection", "close")
        h.end_headers()
        h.close_connection = True
        try:
            h.wfile.write(b": connected\n\n")
            h.wfile.flush()
            while True:
                event = q.get()
                if event is None:
                    return
                h.wfile.write(f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
                h.wfile.flush()
        except OSError:
            pass
        finally:
            with self._lock:
                self._listeners.remove(q)
