"""
Talking to the farm's Prusa Connect server over its REST API (version 1; the server serves its reference at /docs).

Pairing: the plugin asks for a token (POST /api/v1/auth/app-pairings) and gets a short code; someone signed in to
Prusa Connect approves it on Prusa Connect's own page, and the plugin collects the token (POST .../token). Nobody types
a password or pastes a secret. The token is limited to the "read" scope: the plugin only reads printers' state.

Prusa Connect keeps each printer's state as a tree of paths ("/state", "/job/progress", "/temperature/bed"...) in the
words the printer's firmware uses, which are PrusaLink's too (PRINTING, IDLE, FINISHED...): report() turns one into the
report Farmhand takes (PUT /plugin-api/v1/printers/{id}/status).

Prusa Connect is a public beta (0.x): its API can change between releases. Every failure is a ConnectError in words
for the operator.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

from .config import Settings

TIMEOUT = 8
APP_NAME = "Farmhand"
SCOPES = ["read"]


class ConnectError(Exception):
    """kind: "setup" (no address, or not paired) | "refused" (the token) | "down" | "not_found" | "error"."""

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.message, self.kind = message, kind


class PrusaConnect:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ------------------------------------------------------------------ the server

    def health(self) -> dict:
        """GET /api/v1/health: {status, version}. Needs no token."""
        return self._call("GET", "/api/v1/health", auth=False)

    def start_pairing(self) -> dict:
        """Ask for a token: the short code to approve on Prusa Connect's page. Returns the pairing as the page shows it."""
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

    # ------------------------------------------------------------------ the plumbing

    def _call(self, method: str, path: str, body=None, auth: bool = True) -> dict:
        status, data = self._raw(method, path, body, auth)
        if status == 401 and auth:
            raise ConnectError(
                "Prusa Connect refused the plugin's token (it may have been revoked, or run out after 90 days). Pair "
                "the plugin with Prusa Connect again on this page.", "refused",
            )
        if status == 403:
            raise ConnectError(f"Prusa Connect won't let the plugin see that: {_words(data) or 'access denied'}.", "refused")
        if status == 404:
            raise ConnectError("Prusa Connect doesn't know that printer any more (it may have been paired again).", "not_found")
        if status >= 400:
            raise ConnectError(f"Prusa Connect answered {status}: {_words(data)}", "error")
        if not isinstance(data, dict):
            raise ConnectError("The server answered, but not like Prusa Connect does.", "error")
        return data

    def _raw(self, method: str, path: str, body=None, auth: bool = True):
        base = self.settings.address
        if not base:
            raise ConnectError("Prusa Connect's address isn't set yet. Type it on this page.", "setup")
        headers = {"Accept": "application/json"}
        if auth:
            token = self.settings.token
            if not token:
                raise ConnectError("The plugin isn't paired with Prusa Connect yet. Pair it on this page.", "setup")
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
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


def device_out(device: dict) -> dict:
    """A Prusa Connect printer as the plugin's page lists it."""
    state = device.get("state") if isinstance(device.get("state"), dict) else {}
    return {
        "id": device.get("id"), "name": device.get("name"), "model": device.get("model"), "serial": device.get("serial"),
        "firmware": device.get("firmware"), "connected": bool(device.get("connected")), "state": state.get("/state"),
    }
