"""
Stand-ins for the two servers the plugin talks to, each a real HTTP server on a free port:

    FakeFarmhand       Farmhand's plugin API (/plugin-api/v1): GET /printers and PUT /printers/{id}/status, with the
                       token and permissions checked as Farmhand does (docs/plugins.md)
    FakePrusaConnect   a Prusa Connect server's REST API: health, pairing with a short code, the printers it knows.
                       Written from Prusa Connect's API reference; none of its code is used.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "good-token"
DEVICE = "0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"


class _Server:
    def __init__(self, prefix: str = ""):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _go(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                fake.calls.append((self.command, self.path))
                status, answer = fake.answer(self.command, self.path, self.headers, body)
                data = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = _go

            def log_message(self, *args):
                pass

        self.calls: list[tuple[str, str]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}{prefix}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class FakeFarmhand(_Server):
    def __init__(self):
        self.printers = [
            {"id": 1, "name": "VT 1190", "kind": "Voron", "connection_type": "moonraker", "status_from": None, "addresses": {}},
            {"id": 2, "name": "Core One", "kind": "Prusa Core One", "connection_type": "prusalink", "status_from": "prusa-connect", "addresses": {}},
            {"id": 3, "name": "MK4", "kind": "Prusa MK4", "connection_type": "prusalink", "status_from": None, "addresses": {}},
        ]
        self.permissions = {"printers:read", "printers:report"}
        self.reports: dict[int, list[dict]] = {}
        super().__init__("/plugin-api/v1")

    def answer(self, method, path, headers, body):
        if headers.get("Authorization") != f"Bearer {TOKEN}":
            return 401, {"detail": "That plugin token isn't valid: it was replaced by a new one."}
        path = path.removeprefix("/plugin-api/v1")
        if method == "GET" and path == "/printers":
            if "printers:read" not in self.permissions:
                return 403, {"detail": "The \"prusa-connect\" plugin hasn't been given the printers:read permission, which this needs."}
            return 200, {"printers": self.printers}
        if method == "PUT" and path.startswith("/printers/") and path.endswith("/status"):
            pid = int(path.split("/")[2])
            printer = next((p for p in self.printers if p["id"] == pid), None)
            if printer is None:
                return 404, {"detail": "Printer not found"}
            if printer["status_from"] != "prusa-connect":
                return 403, {"detail": f"Farmhand takes {printer['name']}'s status from its PrusaLink, not this plugin."}
            self.reports.setdefault(pid, []).append(body)
            return 200, {"recorded": body.get("reachable", True), "error": None if body.get("reachable", True) else body.get("error")}
        return 404, {"detail": "Not Found"}


class FakePrusaConnect(_Server):
    def __init__(self):
        self.token = "pcl_test_token"
        self.pairing = None  # "pending" | "approved" | "denied" | "expired"
        self.open = False  # set up in open mode: nobody signs in, and no call needs a token
        self.pairing_requests: list[dict] = []
        self.devices = {DEVICE: {
            "id": DEVICE, "kind": "printer", "model": "COREONE", "serial": "CZPX1234X004XC12345", "name": "Core One",
            "firmware": "6.4.0", "connected": True,
            "state": {"/state": "IDLE", "/temperature/bed": 22, "/temperature/bed_target": 0,
                      "/tools/0/nozzle_temp": 24, "/tools/0/nozzle_target_temp": 0},
        }}
        super().__init__()

    def start_job(self, job_id, path, progress, time_printing, state="PRINTING"):
        d = self.devices[DEVICE]
        d["state"].update({"/state": state, "/job/id": job_id, "/job/path": path, "/job/progress": progress,
                           "/job/state": state, "/job/time_printing": time_printing, "/job/time_remaining": 1800,
                           "/tools/0/nozzle_target_temp": 215, "/temperature/bed_target": 60})
        d["job"] = {"device_job_id": str(job_id), "path": path, "display_name": path.rsplit("/", 1)[-1], "progress": progress}

    def answer(self, method, path, headers, body):
        if path == "/api/v1/health":
            return 200, {"status": "ok", "version": "0.2.0"}
        if path == "/api/v1/auth/info":
            if self.open:
                return 200, {"provider": "", "credentials": False, "redirect": False, "needs_setup": False}
            return 200, {"provider": "local", "credentials": True, "redirect": False, "needs_setup": False}
        if method == "POST" and path == "/api/v1/auth/app-pairings":
            self.pairing_requests.append(body)
            self.pairing = "pending"
            return 201, {"device_code": "secret-device-code", "user_code": "BCDF-GHJK", "expires_in": 600, "interval": 5,
                         "verification_uri": f"{self.url}/pair", "verification_uri_complete": f"{self.url}/pair?code=BCDF-GHJK"}
        if method == "POST" and path == "/api/v1/auth/app-pairings/token":
            if (body or {}).get("device_code") != "secret-device-code" or self.pairing is None:
                return 400, {"code": "core.auth/APP_PAIRING_UNKNOWN", "detail": "unknown"}
            if self.pairing == "approved":
                self.pairing = None
                return 200, {"token": self.token, "origin": "app_pairing", "scopes": ["read"]}
            code = {"pending": "APP_PAIRING_PENDING", "denied": "APP_PAIRING_DENIED", "expired": "APP_PAIRING_EXPIRED"}[self.pairing]
            if self.pairing != "pending":
                self.pairing = None
            return 400, {"code": f"core.auth/{code}", "detail": code.lower()}
        if not self.open and headers.get("Authorization") != f"Bearer {self.token}":
            return 401, {"code": "core.auth/UNAUTHENTICATED", "detail": "no credential"}
        if method == "GET" and path.split("?")[0] == "/api/v1/devices":
            return 200, {"items": list(self.devices.values()), "total": len(self.devices)}
        return 404, {"detail": "not in the fake"}
