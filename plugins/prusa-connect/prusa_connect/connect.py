"""
Talking to the farm's Prusa Connect server over its REST API (version 1; the server serves its reference at /docs).

Pairing: the plugin asks for a token (POST /api/v1/auth/app-pairings) and gets a short code; someone signed in to
Prusa Connect approves it on Prusa Connect's own page, and the plugin collects the token (POST .../token). Nobody types
a password or pastes a secret. The token has the "read" and "operate" scopes: the plugin reads printers' state and
starts the prints Farmhand sends (it uploads each into Prusa Connect, which sends it on to the printer).
A Prusa Connect set up in open mode (its first-run wizard's "no sign-in") has nobody to approve a pairing and asks no
token of anyone: the plugin then reads it without one (is_open()).

Prusa Connect keeps each printer's state as a tree of paths ("/state", "/job/progress", "/temperature/bed"...) in the
words the printer's firmware uses, which are PrusaLink's too (PRINTING, IDLE, FINISHED...): report() turns one into the
report Farmhand takes (PUT /plugin-api/v1/printers/{id}/status).

Prusa Connect is a public beta (0.x): its API can change between releases. Every failure is a ConnectError in words
for the operator.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

from .config import Settings

TIMEOUT = 8
UPLOAD_TIMEOUT = 300  # a big G-code into Prusa Connect
PRINT_TIMEOUT = 900  # Prusa Connect answers once the printer has the file and started it: as long as the transfer
APP_NAME = "Farmhand"
SCOPES = ["read", "operate"]  # reading the printers, and starting the prints Farmhand sends


class ConnectError(Exception):
    """kind: "setup" (no address, or not paired) | "refused" (the token) | "down" | "not_found" | "error"."""

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.message, self.kind = message, kind


OPEN_CHECK_SECONDS = 60


class PrusaConnect:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._open: tuple[str, bool, float] | None = None  # (address, open?, when asked)

    # ------------------------------------------------------------------ the server

    def health(self) -> dict:
        """GET /api/v1/health: {status, version}. Needs no token."""
        return self._call("GET", "/api/v1/health", auth=False)

    def is_open(self) -> bool:
        """Does this Prusa Connect let anyone in without signing in (open mode)? GET /api/v1/auth/info, asked once a minute."""
        address = self.settings.address
        if not address:
            return False
        now = time.monotonic()
        if self._open and self._open[0] == address and now - self._open[2] < OPEN_CHECK_SECONDS:
            return self._open[1]
        status, info = self._raw("GET", "/api/v1/auth/info", auth=False)
        is_open = (status == 200 and isinstance(info, dict) and not info.get("provider")
                   and not info.get("credentials") and not info.get("needs_setup"))
        self._open = (address, is_open, now)
        return is_open

    def start_pairing(self) -> dict:
        """Ask for a token: the short code to approve on Prusa Connect's page. Returns the pairing as the page shows it."""
        if self.is_open():
            raise ConnectError("This Prusa Connect lets anyone in without signing in, so the plugin needs no pairing: "
                               "it reads Prusa Connect's printers already.", "setup")
        data = self._call("POST", "/api/v1/auth/app-pairings", {"app_name": APP_NAME, "scopes": SCOPES}, auth=False)
        if not data.get("device_code") or not data.get("user_code"):
            raise ConnectError("Prusa Connect didn't give a pairing code.", "error")
        expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=int(data.get("expires_in") or 600))
        pairing = {
            "device_code": data["device_code"], "user_code": data["user_code"],
            "verification_uri": data.get("verification_uri"), "verification_uri_complete": data.get("verification_uri_complete"),
            "interval": int(data.get("interval") or 5), "expires_at": expires.isoformat().replace("+00:00", "Z"),
        }
        self.settings.set_pairing(pairing)
        return shown_pairing(pairing)

    def check_pairing(self) -> dict:
        """Has the code been approved? {state: paired | pending | denied | expired | none, message}."""
        pairing = self.settings.pairing
        if not pairing:
            return {"state": "paired" if self.settings.token else "none", "message": None}
        status, body = self._raw("POST", "/api/v1/auth/app-pairings/token", {"device_code": pairing["device_code"]}, auth=False)
        if status == 200 and isinstance(body, dict) and body.get("token"):
            self.settings.set_token(body["token"])
            return {"state": "paired", "message": None}
        code = str(body.get("code") or "") if isinstance(body, dict) else ""
        if code.endswith(("APP_PAIRING_PENDING", "APP_PAIRING_SLOW_DOWN")):
            return {"state": "pending", "message": None}
        self.settings.set_pairing(None)
        if code.endswith("APP_PAIRING_DENIED"):
            return {"state": "denied", "message": "Someone turned the pairing down on Prusa Connect. Start again if that was a mistake."}
        if code.endswith(("APP_PAIRING_EXPIRED", "APP_PAIRING_UNKNOWN")):
            return {"state": "expired", "message": "The code ran out before it was approved. Start pairing again."}
        raise ConnectError(f"Prusa Connect answered {status}: {_words(body)}", "error")

    def devices(self) -> list[dict]:
        """Every printer paired with Prusa Connect (retired ones left out), as it gives them."""
        data = self._call("GET", "/api/v1/devices?" + urlencode({"limit": 200}))
        return [d for d in (data.get("items") or []) if isinstance(d, dict) and not d.get("retired")]

    def device(self, device_id: str) -> dict:
        return self._call("GET", f"/api/v1/devices/{quote(device_id)}")

    # ------------------------------------------------------------------ starting a print Farmhand sends

    def printer_storage(self, device_id: str) -> str:
        """Where on the printer a print goes: the first storage it reported that can be written (its USB stick)."""
        found = self._call("GET", f"/api/v1/devices/{quote(device_id)}/storages").get("items") or []
        for s in found:
            if isinstance(s, dict) and s.get("name") and not s.get("read_only"):
                return str(s["name"])
        raise ConnectError("The printer hasn't told Prusa Connect of anywhere to put a print (is its USB stick in?).", "error")

    def upload(self, name: str, data, size: int) -> tuple[str, str]:
        """Put the G-code in Prusa Connect's own storage, as a temporary copy on its way to a printer. (storage, path)."""
        storages = self._call("GET", "/api/v1/storages").get("items") or []
        storage = next((s.get("name") for s in storages if isinstance(s, dict) and s.get("write")), None)
        if not storage:
            raise ConnectError("Prusa Connect has no storage it can keep a print in on its way to the printer. Give it "
                               "one in its settings.", "error")
        query = urlencode({"path": f"farmhand/{name}", "temporary": "true"})
        saved = self._call("PUT", f"/api/v1/storages/{quote(storage)}/content?{query}", stream=(data, size))
        return storage, str(saved.get("path") or f"farmhand/{name}")

    def print_file(self, device_id: str, storage: str, source: str, path: str) -> str:
        """Send the stored file to the printer at `path` (replacing one of that name) and start it. Returns `path`."""
        result = self._call("POST", f"/api/v1/devices/{quote(device_id)}/print",
                            {"path": path, "storage": storage, "source": source, "replace": True}, timeout=PRINT_TIMEOUT)
        command = result.get("command") or {}
        if command.get("ok") is False:
            raise ConnectError(f"The printer turned the print down: {_words(command) or 'it gave no reason'}.", "refused_print")
        return str(result.get("path") or path)

    # ------------------------------------------------------------------ the plumbing

    def _call(self, method: str, path: str, body=None, auth: bool = True, stream=None, timeout: float = None) -> dict:
        status, data = self._raw(method, path, body, auth, stream=stream, timeout=timeout)
        if status == 401 and auth:
            raise ConnectError(
                "Prusa Connect refused the plugin's token (it may have been revoked, or run out after 90 days). Pair "
                "the plugin with Prusa Connect again on this page.", "refused",
            )
        if status == 403:
            raise ConnectError(f"Prusa Connect won't let the plugin see that: {_words(data) or 'access denied'}.", "refused")
        if status == 404:
            raise ConnectError("Prusa Connect doesn't know that printer any more (it may have been paired again).", "not_found")
        if status == 409:
            raise ConnectError(f"Prusa Connect says the printer can't take that now: {_words(data)}", "busy")
        if status >= 400:
            raise ConnectError(f"Prusa Connect answered {status}: {_words(data)}", "error")
        if not isinstance(data, dict):
            raise ConnectError("The server answered, but not like Prusa Connect does.", "error")
        return data

    def _raw(self, method: str, path: str, body=None, auth: bool = True, stream=None, timeout: float = None):
        base = self.settings.address
        if not base:
            raise ConnectError("Prusa Connect's address isn't set yet. Type it on this page.", "setup")
        headers = {"Accept": "application/json"}
        if auth:
            token = self.settings.token
            if token:
                headers["Authorization"] = f"Bearer {token}"
            elif not self.is_open():
                raise ConnectError("The plugin isn't paired with Prusa Connect yet. Pair it on this page.", "setup")
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif stream is not None:  # (open file, size): sent a piece at a time
            data, size = stream
            headers["Content-Type"] = "application/octet-stream"
            headers["Content-Length"] = str(size)
        request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout or (UPLOAD_TIMEOUT if stream is not None else TIMEOUT)) as answer:
                return answer.status, _json(answer.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, _json(e.read())
            except OSError:
                return e.code, None
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", None) or e
            why = "it didn't answer in time" if "timed out" in str(reason) else str(reason)
            raise ConnectError(f"Can't reach Prusa Connect at {base} ({why}). Is it running?", "down") from None


def _json(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8") or "null")
    except ValueError:
        return None


def _words(body) -> str:
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("title") or body.get("code") or "")[:300]
    return ""


def shown_pairing(pairing: dict | None) -> dict | None:
    """What the page shows of a pairing that's waiting: never the device code, which is the secret half."""
    if not pairing:
        return None
    return {k: pairing.get(k) for k in ("user_code", "verification_uri", "verification_uri_complete", "expires_at", "interval")}


# ------------------------------------------------------------------ a printer's state, as Farmhand takes it


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _job_number(state: dict, summary: dict):
    raw = state.get("/job/id", summary.get("device_job_id"))
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def report(device: dict | None, link: str | None = None, error: str | None = None) -> dict:
    """
    Farmhand's report of a printer (docs/plugins.md, "Reporting a printer's status") from Prusa Connect's record of it.
    No device (or one Prusa Connect isn't hearing from) is reported unreachable, with why.
    """
    if device is None:
        return {"reachable": False, "error": error or "Prusa Connect couldn't be asked about this printer.", "link": link}
    name = device.get("name") or "the printer"
    if not device.get("connected"):
        return {
            "reachable": False, "link": link,
            "error": f"Prusa Connect isn't hearing from {name} right now. Is it switched on, and still paired with Prusa Connect?",
        }
    state = device.get("state") if isinstance(device.get("state"), dict) else {}
    summary = device.get("job") if isinstance(device.get("job"), dict) else {}
    out = {
        "reachable": True, "error": None, "link": link,
        "state": state.get("/state"),
        "temps": {
            "temp_nozzle": _num(state.get("/tools/0/nozzle_temp", state.get("/temperature/nozzle"))),
            "target_nozzle": _num(state.get("/tools/0/nozzle_target_temp", state.get("/temperature/nozzle_target"))),
            "temp_bed": _num(state.get("/temperature/bed")),
            "target_bed": _num(state.get("/temperature/bed_target")),
        },
        "printer_type": device.get("model"), "firmware": device.get("firmware"),
        "job": None,
        "extras": extras(state),
    }
    number = _job_number(state, summary)
    if number is not None:
        path = state.get("/job/path") or summary.get("path") or ""
        remaining = _num(state.get("/job/time_remaining"))
        if remaining is None and _num(summary.get("time_remaining_ms")) is not None:
            remaining = summary["time_remaining_ms"] / 1000
        progress = _num(state.get("/job/progress", summary.get("progress")))
        out["job"] = {
            "id": number,
            "state": state.get("/job/state") or summary.get("state") or state.get("/state"),
            "file": summary.get("display_name") or (path.rsplit("/", 1)[-1] if path else None),
            "path": path or None,
            "progress": max(0.0, min(100.0, float(progress))) if progress is not None else None,
            "time_printing": _num(state.get("/job/time_printing")),
            "time_remaining": remaining if remaining is None or remaining >= 0 else None,
        }
    return out


MATERIAL = "/tools/0/material_package_instance/package/material/abbreviation"


def _flag(value):
    return value if isinstance(value, bool) else None


def _text(value, most: int):
    return str(value)[:most] if value not in (None, "") else None


def extras(state: dict) -> dict:
    """What Prusa Connect knows of the printer beyond PrusaLink: the loaded material, the nozzle, the chamber, fans,
    speed and flow, a message on its screen, and the extruder's odometer (mm fed, ever), which Farmhand measures each
    print's filament with."""
    dialog = None
    if state.get("/dialog/id") is not None or state.get("/dialog/code") is not None:
        dialog = {"code": _text(state.get("/dialog/code"), 40), "title": _text(state.get("/dialog/title"), 200),
                  "text": _text(state.get("/dialog/text"), 1000)}
    nozzle = _num(state.get("/tools/0/features/nozzle_diameter"))
    return {
        "material": _text(state.get(MATERIAL), 40),
        "nozzle_diameter": nozzle if nozzle and 0 < nozzle <= 5 else None,
        "nozzle_hardened": _flag(state.get("/tools/0/features/nozzle_hardened")),
        "nozzle_high_flow": _flag(state.get("/tools/0/features/nozzle_high_flow")),
        "temp_chamber": _num(state.get("/temperature/chamber")),
        "target_chamber": _num(state.get("/temperature/chamber_target")),
        "print_fan_rpm": _positive(state.get("/tools/0/print_fan_rpm")),
        "heatbreak_fan_rpm": _positive(state.get("/tools/0/heatbreak_fan_rpm")),
        "speed": _positive(state.get("/speed")),
        "flow": _positive(state.get("/flow")),
        "odometer_e": _positive(state.get("/tools/0/odometer_e")),
        "dialog": dialog,
    }


def _positive(value):
    value = _num(value)
    return value if value is not None and value >= 0 else None


def device_out(device: dict) -> dict:
    """A Prusa Connect printer as the plugin's page lists it."""
    state = device.get("state") if isinstance(device.get("state"), dict) else {}
    return {
        "id": device.get("id"), "name": device.get("name"), "model": device.get("model"), "serial": device.get("serial"),
        "firmware": device.get("firmware"), "connected": bool(device.get("connected")), "state": state.get("/state"),
    }
