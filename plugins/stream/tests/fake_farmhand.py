"""
A stand-in for Farmhand's plugin API (/plugin-api/v1), answering in exactly its shapes (docs/plugins.md): the token
checked, permissions checked, 429 on demand, the farm's cameras, each printer's print, and stream:migrate's one-off
hand-over. Copied from the Hello plugin's tests, with what the Stream plugin reads added. `down` makes it answer
nothing at all, as a stopped Farmhand.
"""
from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "good-token"
EVERYTHING = {"printers:read", "prints:read", "farm:read", "cameras:read", "stream:migrate"}
MJPEG = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "5",
         "-rw_timeout", "10000000", "-use_wallclock_as_timestamps", "1", "-f", "mpjpeg"]


def camera(name: str, url: str, error: str | None = None, rotation: int = 0) -> dict:
    """A camera as Farmhand's /cameras gives it."""
    return {"name": name, "kind": None if error else "mjpeg", "url": None if error else url,
            "ffmpeg_input": None if error else [*MJPEG, "-i", url], "rotation": rotation, "flip_horizontal": False,
            "flip_vertical": False, "ffmpeg_filters": ["transpose=1"] if rotation == 90 else [], "aspect_ratio": "4:3",
            "target_fps": 15, "snapshot_url": None, "error": error}


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
        self.cameras = {
            1: {"printer_id": 1, "printer_name": "VT 1190", "error": None,
                "cameras": [camera("Bed", "http://10.0.6.21/webcam/?action=stream")]},
            2: {"printer_id": 2, "printer_name": "Core One", "error": None,
                "cameras": [camera("Camera", "http://10.0.6.30/stream"), camera("Nozzle", "", error="Core One's Nozzle camera only plays in a browser (WebRTC).")]},
        }
        self.migration = {
            "settings": {"cols": 2, "rows": 1, "cells": [{"camera": "1:Bed"}, None], "title": "The farm", "border_color": "#FF8800"},
            "layouts": [{"name": "Morning", "cols": 1, "rows": 1, "cells": [{"camera": "1:Bed"}]}],
            "stream_key": "abcd-efgh-ijkl", "stream_folder": "/data/nas/farmhand/stream",
            "youtube": {"client": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-secret"},
                        "refresh_token": "1//refresh", "channel": "Print Farm", "stream_id": "own-stream"},
        }
        self.handed_over_at: str | None = None
        self.down = False  # True: nothing answers (Farmhand stopped)
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
                if fake.down:
                    return self.close_connection_now()
                fake.answer(self)

            def do_POST(self):
                fake.calls.append("POST " + self.path)
                if fake.down:
                    return self.close_connection_now()
                fake.answer(self, post=True)

            def close_connection_now(self):
                self.close_connection = True
                try:
                    self.connection.shutdown(2)
                except OSError:
                    pass

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

    def answer(self, h: BaseHTTPRequestHandler, post: bool = False):
        if h.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self.send(h, 401, {"detail": "That plugin token isn't valid: it was replaced by a new one."})
        if self.busy_for > 0:
            self.busy_for -= 1
            return self.send(h, 429, {"detail": "This plugin is asking Farmhand too often."}, {"Retry-After": "1"})
        path = h.path.removeprefix("/plugin-api/v1")
        if path == "/me":
            return self.send(h, 200, {"plugin_id": "stream", "permissions": sorted(self.permissions), "api_version": "1"})
        if path == "/cameras":
            return self.allowed(h, "cameras:read") and self.send(h, 200, {"printers": list(self.cameras.values())})
        if path == "/stream/migrate":
            if not self.allowed(h, "stream:migrate"):
                return True
            if not post:
                return self.send(h, 200, {"available": self.handed_over_at is None, "handed_over_at": self.handed_over_at, "has_settings": True})
            if self.handed_over_at:
                return self.send(h, 410, {"detail": "Farmhand already handed its Stream page set-up to this plugin, and hands it over only once."})
            self.handed_over_at = "2026-11-11T10:00:00+00:00"
            return self.send(h, 200, {**self.migration, "handed_over_at": self.handed_over_at})
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
        self.send(h, 403, {"detail": f"The \"stream\" plugin hasn't been given the {permission} permission, which this needs."})
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
