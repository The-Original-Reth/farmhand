"""
Talking to Farmhand's plugin API (docs/plugins.md in Farmhand's repository has every endpoint and answer), with the
token as "Authorization: Bearer <FARMHAND_TOKEN>". Whatever goes wrong is a FarmhandError in words for the operator:

    401  Farmhand doesn't know the token (replaced, plugin removed or switched off)
    403  a permission the operator didn't grant, or a printer that doesn't take its status from this plugin
    429  asked too often: wait Retry-After seconds
    no answer: Farmhand is down or restarting, or FARMHAND_URL is wrong
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

CALL_TIMEOUT = 15


class FarmhandError(Exception):
    """kind: "setup" | "refused" (401) | "forbidden" (403) | "busy" (429) | "down" | "error". short: for /health."""

    def __init__(self, message: str, kind: str, retry_after: float | None = None, short: str | None = None):
        super().__init__(message)
        self.message, self.kind, self.retry_after = message, kind, retry_after
        self.short = short or message


class Farmhand:
    def __init__(self, url: str, token: str):
        self.url, self.token = url, token

    def printers(self) -> list[dict]:
        """GET /printers (printers:read): every printer in service, with status_from (this plugin's id when Farmhand
        takes the printer's status from it)."""
        return self._call("GET", "/printers")["printers"]

    def report(self, printer_id: int, report: dict) -> dict:
        """PUT /printers/{id}/status (printers:report): a printer's status, in PrusaLink's words. {recorded, error}."""
        return self._call("PUT", f"/printers/{printer_id}/status", report)

    # ------------------------------------------------------------------ the plumbing

    def _call(self, method: str, path: str, body=None) -> dict:
        if not self.url:
            raise FarmhandError(
                "FARMHAND_URL isn't set, so this plugin doesn't know where Farmhand is. Add the plugin on Farmhand's "
                "Plugins page, then start its container again with the two lines it shows you.", "setup",
                short="FARMHAND_URL isn't set: add the plugin on Farmhand's Plugins page.",
            )
        if not self.token:
            raise FarmhandError(
                "FARMHAND_TOKEN isn't set. Add the plugin on Farmhand's Plugins page (or make it a new token there), "
                "then start its container again with the FARMHAND_TOKEN it shows you.", "setup",
                short="FARMHAND_TOKEN isn't set: add the plugin on Farmhand's Plugins page.",
            )
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=CALL_TIMEOUT) as answer:
                return json.loads(answer.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            raise _refusal(e) from None
        except (urllib.error.URLError, OSError) as e:
            raise FarmhandError(f"Can't reach Farmhand at {self.url} ({_reason(e)}).", "down") from None


def _refusal(e: urllib.error.HTTPError) -> FarmhandError:
    detail = _detail(e)
    if e.code == 401:
        words = ("Farmhand refused this plugin's token: make a new one on Farmhand's Plugins page, put it in "
                 "prusa-connect.env as FARMHAND_TOKEN and start the plugin's container again.")
        return FarmhandError(f"{words} (Farmhand said: {detail})", "refused", short=words)
    if e.code == 403:
        return FarmhandError(detail or "Farmhand won't let this plugin do that.", "forbidden",
                             short=detail[:200] if detail else None)
    if e.code == 429:
        try:
            wait = float(e.headers.get("Retry-After", "5"))
        except ValueError:
            wait = 5.0
        return FarmhandError(f"Farmhand asked this plugin to slow down; trying again in {wait:g} s.", "busy", wait)
    if e.code in (502, 503, 504):
        return FarmhandError(f"Farmhand isn't ready (it answered {e.code}); it may be starting up.", "down")
    return FarmhandError(f"Farmhand answered {e.code}: {detail}", "error")


def _detail(e: urllib.error.HTTPError) -> str:
    try:
        body = e.read().decode("utf-8", "replace")
    except OSError:
        return str(e.reason or "")
    try:
        detail = json.loads(body)["detail"]
        return detail if isinstance(detail, str) else json.dumps(detail)[:300]
    except (ValueError, KeyError, TypeError):
        return body.strip()[:300] or str(e.reason or "")


def _reason(e: Exception) -> str:
    reason = getattr(e, "reason", None) or e
    if isinstance(reason, TimeoutError) or "timed out" in str(reason):
        return "it didn't answer in time"
    if isinstance(reason, ConnectionRefusedError):
        return "nothing is listening there; is it running?"
    return str(reason) or type(reason).__name__
