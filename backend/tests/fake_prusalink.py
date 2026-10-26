"""
A stand-in for a Prusa Core One's PrusaLink, enough of it to test Farmhand against: version, status, the current job,
storage, and uploading a file to print. It checks the HTTP digest login the way the printer does. Plug it in with
`prusalink.client.transport = httpx.MockTransport(fake.handle)`.
"""
from __future__ import annotations

import hashlib
import re

import httpx

REALM = "Printer API"
NONCE = "a1b2c3d4"


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


class FakePrusaLink:
    def __init__(self, username="maker", password="secret123"):
        self.username, self.password = username, password
        self.state = "IDLE"
        self.job: dict | None = None  # {id, state, progress, time_printing, time_remaining, file: {...}}
        self.usb_present = True
        self.uploads: list[dict] = []  # {path, size, headers}
        self.down = False  # True: behaves like a printer that's switched off
        self.requests: list[tuple[str, str]] = []

    def start_job(self, job_id: int, name: str, *, progress=0.0, time_printing=0, time_remaining=3600, state="PRINTING"):
        self.state = state
        self.job = {
            "id": job_id, "state": state, "progress": progress, "time_printing": time_printing,
            "time_remaining": time_remaining, "inaccurate_estimates": False,
            "file": {"name": name.lower()[:8] + "~1.BGC", "display_name": name, "path": "/usb", "size": 123456,
                     "m_timestamp": 1_700_000_000, "meta": {"filament_type": "PETG", "layer_height": 0.2}},
        }

    def advance(self, *, progress: float, time_printing: int, state="PRINTING"):
        self.job.update(progress=progress, time_printing=time_printing, state=state,
                        time_remaining=0 if state != "PRINTING" else self.job["time_remaining"])
        self.state = state

    def clear_job(self):
        self.job = None
        self.state = "IDLE"

    # ------------------------------------------------------------------ the HTTP side

    def _authorized(self, request: httpx.Request) -> bool:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Digest "):
            return False
        f = dict(re.findall(r'(\w+)="?([^",]*)"?', header[7:]))
        if f.get("username") != self.username or f.get("nonce") != NONCE:
            return False
        ha1 = _md5(f"{self.username}:{REALM}:{self.password}")
        ha2 = _md5(f"{request.method}:{f.get('uri')}")
        if f.get("qop"):
            expected = _md5(f"{ha1}:{NONCE}:{f.get('nc')}:{f.get('cnonce')}:{f.get('qop')}:{ha2}")
        else:
            expected = _md5(f"{ha1}:{NONCE}:{ha2}")
        return f.get("response") == expected

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        self.requests.append((request.method, request.url.path))
        if not self._authorized(request):
            return httpx.Response(401, headers={"WWW-Authenticate": f'Digest realm="{REALM}", nonce="{NONCE}", qop="auth"'})
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"api": "2.0.0", "server": "2.1.2", "text": "PrusaLink", "firmware": "6.2.0", "printer": "COREONE"})
        if path == "/api/v1/status":
            body = {"printer": {"state": self.state, "temp_nozzle": 215.2, "target_nozzle": 215.0, "temp_bed": 60.1, "target_bed": 60.0}}
            if self.job:
                body["job"] = {k: self.job[k] for k in ("id", "progress", "time_printing", "time_remaining")}
            return httpx.Response(200, json=body)
        if path == "/api/v1/job":
            return httpx.Response(200, json=self.job) if self.job else httpx.Response(204)
        if path == "/api/v1/storage":
            usb = {"name": "usb", "type": "USB", "path": "/usb", "available": self.usb_present, "read_only": False, "free_space": 10**9}
            return httpx.Response(200, json={"storage_list": [usb]})
        if path.startswith("/api/v1/files/") and request.method == "PUT":
            if self.state not in ("IDLE", "READY", "FINISHED", "STOPPED"):
                return httpx.Response(409)
            raw_path = request.url.raw_path.decode().split("?")[0]  # as sent, still percent-encoded
            self.uploads.append({"path": raw_path, "size": len(request.content), "headers": dict(request.headers)})
            if request.headers.get("Print-After-Upload") == "?1":
                self.start_job((self.job or {}).get("id", 0) + 1, path.rsplit("/", 1)[-1])
            return httpx.Response(201)
        return httpx.Response(404)
