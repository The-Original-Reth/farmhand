"""
A stand-in for a printer's Moonraker, enough of it to test Farmhand against: server info, job history (paged,
newest first), job totals, and the database items Mainsail keeps maintenance reminders in. Plug it in with
`moonraker.client.transport = httpx.MockTransport(fake.handle)`.
"""
from __future__ import annotations

import json
import re

import httpx


class FakeMoonraker:
    def __init__(self):
        self.jobs: list[dict] = []  # oldest first, as Moonraker records them
        self.totals = {
            "total_jobs": 0, "total_time": 0.0, "total_print_time": 0.0, "total_filament_used": 0.0,
            "longest_job": 0.0, "longest_print": 0.0,
        }
        self.db: dict[str, dict] = {}  # namespace -> {key: value}
        self.api_key: str | None = None  # when set, requests without this X-Api-Key are refused
        self.down = False  # True: behaves like a printer that's switched off
        self.hostname = "mainsail"  # the machine's name, as Klipper's /printer/info gives it
        self.app = "Klipper"  # ...and what it says it is (a Kalico printer says "Kalico")
        # Its network interfaces, as /machine/system_info lists them: {name: [ipv4 address, ...]}; None = won't say
        self.interfaces: dict[str, list[str]] | None = {}
        self.requests: list[tuple[str, str]] = []
        # A power meter like a smart plug over MQTT: None = the printer has none (and no [sensor] at all)
        self.meter_kwh: float | None = None
        self.print_state = "standby"  # Klipper's print_stats state: standby | printing | paused | complete | ...
        # The print running now (with print_state "printing" or "paused"): its file, seconds printed, progress 0..1
        self.live = {"filename": "", "print_duration": 0.0, "progress": 0.0}
        self.temps = {"extruder": (24.0, 0.0), "heater_bed": (23.0, 0.0)}  # (temperature, target)
        self.uploads: list[dict] = []  # {filename, size, root, print}
        self.webcams: list[dict] = []  # as Mainsail's camera settings save them

    def add_job(self, job_id: str, filename: str, *, status="completed", start=1_700_000_000.0, print_s=3600.0,
                filament_mm=5000.0, energy_kwh: float | None = None):
        self.jobs.append({
            "job_id": job_id, "user": None, "filename": filename, "exists": True, "status": status,
            "start_time": start, "end_time": None if status == "in_progress" else start + print_s + 60,
            "print_duration": print_s, "total_duration": print_s + 60, "filament_used": filament_mm,
            "metadata": {"slicer": "PrusaSlicer", "estimated_time": print_s, "layer_height": 0.2, "filament_type": "PLA"},
            "auxiliary_data": [] if energy_kwh is None else [
                {"provider": "sensor powermeter", "name": "energy_consumption", "value": energy_kwh,
                 "description": "Energy consumption", "units": "kWh"},
                {"provider": "sensor powermeter", "name": "average_power", "value": energy_kwh * 1000 / (print_s / 3600),
                 "description": "Average power draw", "units": "W"},
                {"provider": "sensor powermeter", "name": "max_power", "value": 650.0,
                 "description": "Maximum power draw", "units": "W"},
            ],
        })
        if energy_kwh is not None:
            self.energy_total = getattr(self, "energy_total", 0.0) + energy_kwh
        self.totals["total_jobs"] += 1
        self.totals["total_print_time"] += print_s
        self.totals["total_time"] += print_s + 60
        self.totals["total_filament_used"] += filament_mm

    # ------------------------------------------------------------------ the HTTP side

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        self.requests.append((request.method, request.url.path))
        if self.api_key and request.headers.get("X-Api-Key") != self.api_key:
            return self._error(401, "Unauthorized")
        path, q = request.url.path, request.url.params
        if path == "/server/info":
            return self._ok({"klippy_state": "ready", "moonraker_version": "v0.9.3-fake"})
        if path == "/printer/info":
            return self._ok({"state": "ready", "hostname": self.hostname, "app": self.app, "software_version": "v0.12.0-fake"})
        if path == "/machine/system_info":
            if self.interfaces is None:
                return self._error(404, "Not Found")
            network = {name: {"mac_address": f"02:00:00:00:00:{i:02x}", "ip_addresses": [
                {"family": "ipv4", "address": a, "is_link_local": False} for a in addresses
            ]} for i, (name, addresses) in enumerate(self.interfaces.items())}
            return self._ok({"system_info": {"network": network}})
        if path == "/server/history/totals":
            aux = []
            if hasattr(self, "energy_total"):
                aux = [{"provider": "sensor powermeter", "field": "energy_consumption", "maximum": None, "total": self.energy_total}]
            return self._ok({"job_totals": dict(self.totals), "auxiliary_totals": aux})
        if path == "/server/sensors/list":
            if self.meter_kwh is None:
                return self._error(404, "Not Found")  # no [sensor] configured
            return self._ok({"sensors": {"powermeter": {
                "id": "powermeter", "friendly_name": "MiniPMG3", "type": "mqtt",
                "values": {"power": 44.7, "voltage": 123.5, "current": 0.45, "energy": self.meter_kwh},
            }}})
        if path == "/server/history/list":
            jobs = list(reversed(self.jobs)) if q.get("order", "desc") == "desc" else list(self.jobs)
            start, limit = int(q.get("start", 0)), int(q.get("limit", 50))
            page = jobs[start:start + limit]
            return self._ok({"count": len(self.jobs), "jobs": page})
        if path == "/server/database/item":
            return self._database(request)
        if path == "/printer/objects/query":
            status = {"print_stats": {"state": self.print_state, "filename": self.live["filename"], "print_duration": self.live["print_duration"]}}
            if "virtual_sdcard" in q:
                status["virtual_sdcard"] = {"progress": self.live["progress"], "is_active": self.print_state == "printing"}
            for name, (now, target) in self.temps.items():
                if name in q:
                    status[name] = {"temperature": now, "target": target}
            return self._ok({"eventtime": 1.0, "status": status})
        if path == "/server/webcams/list":
            return self._ok({"webcams": self.webcams})
        if path == "/server/files/upload" and request.method == "POST":
            return self._upload(request)
        return self._error(404, "Not Found")

    def _database(self, request: httpx.Request) -> httpx.Response:
        q = request.url.params
        if request.method == "GET":
            ns = q.get("namespace")
            if ns not in self.db:
                return self._error(404, f"Namespace '{ns}' not found")
            key = q.get("key")
            if key is None:
                return self._ok({"namespace": ns, "key": None, "value": dict(self.db[ns])})
            if key not in self.db[ns]:
                return self._error(404, f"Key '{key}' in namespace '{ns}' not found")
            return self._ok({"namespace": ns, "key": key, "value": self.db[ns][key]})
        if request.method == "POST":
            body = json.loads(request.content)
            self.db.setdefault(body["namespace"], {})[body["key"]] = body["value"]
            return self._ok({"namespace": body["namespace"], "key": body["key"], "value": body["value"]})
        if request.method == "DELETE":
            ns, key = q.get("namespace"), q.get("key")
            if ns not in self.db or key not in self.db[ns]:
                return self._error(404, f"Key '{key}' in namespace '{ns}' not found")
            value = self.db[ns].pop(key)
            return self._ok({"namespace": ns, "key": key, "value": value})
        return self._error(405, "Method not allowed")

    def _upload(self, request: httpx.Request) -> httpx.Response:
        # just enough multipart reading for a test: the file's name and size, and the root and print fields
        body = request.content
        name = re.search(rb'name="file"; filename="([^"]+)"', body).group(1).decode()
        fields = dict(re.findall(rb'name="(root|print)"\r\n\r\n([^\r]*)', body))
        part = body.split(b'filename="' + name.encode() + b'"', 1)[1].split(b"\r\n\r\n", 1)[1]
        size = len(part[: part.index(b"\r\n--")])
        self.uploads.append({"filename": name, "size": size, "root": fields.get(b"root", b"").decode(), "print": fields.get(b"print", b"").decode()})
        if fields.get(b"print") == b"true":
            self.print_state = "printing"
        # an upload's answer isn't wrapped in "result"
        return httpx.Response(201, json={"item": {"path": name, "root": "gcodes"}, "print_started": True, "action": "create_file"})

    @staticmethod
    def _ok(result) -> httpx.Response:
        return httpx.Response(200, json={"result": result})

    @staticmethod
    def _error(code: int, message: str) -> httpx.Response:
        return httpx.Response(code, json={"error": {"code": code, "message": message}})
