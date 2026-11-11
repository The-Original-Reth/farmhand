"""
Talking to Farmhand's plugin API (docs/plugins.md in Farmhand's repository has every endpoint and answer).

Every call sends the plugin's token as "Authorization: Bearer <FARMHAND_TOKEN>". Whatever goes wrong becomes a
FarmhandError whose message is plain words for the operator, shown on the plugin's page as it is:

    401  Farmhand doesn't know the token: it was replaced, the plugin was removed or switched off, or it's wrong
    403  the call needs a permission the operator didn't grant, or came from somewhere other than the plugin's address
    429  the plugin asked too often: wait Retry-After seconds
    no answer at all: Farmhand is down or restarting, or FARMHAND_URL is wrong

Farmhand's own error answers are JSON, {"detail": "..."}, already in words meant for the operator, so they're passed on.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator

CALL_TIMEOUT = 15  # seconds; asking a printer that's off can take Farmhand a few
EVENTS_TIMEOUT = 45  # Farmhand sends a comment line every 15 s on /events; this long without one means it's gone


class FarmhandError(Exception):
    """
    Farmhand couldn't be asked, or said no. `message` is for the operator; `kind` is for the code:
    "setup" (an environment variable is missing), "refused" (401), "forbidden" (403), "busy" (429),
    "down" (no answer), "gone" (410: handed over already) or "error" (anything else). `retry_after` is how many seconds to wait, when Farmhand said.
    `short` is the same in fewer words (for /health, which Farmhand's Plugins page shows in a line or two).
    """

    def __init__(self, message: str, kind: str, retry_after: float | None = None, short: str | None = None):
        super().__init__(message)
        self.message, self.kind, self.retry_after = message, kind, retry_after
        self.short = short or message


class Farmhand:
    def __init__(self, url: str, token: str, timeout: float = CALL_TIMEOUT):
        self.url, self.token, self.timeout = url, token, timeout

    # ------------------------------------------------------------------ the endpoints this plugin uses

    def printers(self) -> list[dict]:
        """GET /printers (printers:read): every printer in service, [{id, name, kind, connection_type, addresses}]."""
        return self.get("/printers")["printers"]

    def print_of(self, printer_id: int) -> dict:
        """GET /printers/{id}/print (prints:read): {state, progress, file, error} of the print under way."""
        return self.get(f"/printers/{printer_id}/print")

    def cameras(self) -> dict:
        """GET /cameras (cameras:read): {printers: [{printer_id, printer_name, error, cameras: [{name, kind, url,
        ffmpeg_input, ffmpeg_filters, aspect_ratio, target_fps, snapshot_url, error...}]}]}."""
        return self.get("/cameras")

    def me(self) -> dict:
        """GET /me: {plugin_id, permissions, api_version}."""
        return self.get("/me")

    def stream_migration_state(self) -> dict:
        """GET /stream/migrate (stream:migrate): {available, handed_over_at, has_settings}."""
        return self.get("/stream/migrate")

    def stream_migration(self) -> dict:
        """POST /stream/migrate (stream:migrate): Farmhand's Stream page set-up, handed over once (410 after)."""
        return self.call("POST", "/stream/migrate")

    def farm(self) -> dict:
        """GET /farm (farm:read): {mode, colors, time_zone}, so the page matches Farmhand when opened on its own."""
        return self.get("/farm")

    def events(self) -> Iterator[tuple[str, dict]]:
        """
        GET /events (prints:read): server-sent events, as (type, data) pairs, until the connection drops (then
        FarmhandError "down"). First ("connected", {}), this plugin's own marker that the connection is open. Then
        Farmhand's types: print.started / paused / resumed / finished and printer.reachable /
        unreachable; ignore any you don't know, since new ones may be added.
        """
        with self._open("/events", accept="text/event-stream", timeout=EVENTS_TIMEOUT) as answer:
            yield "connected", {}
            kind, data = "message", []
            try:
                for raw in answer:  # one line at a time, as Farmhand sends them
                    line = raw.decode("utf-8").rstrip("\r\n")
                    if line == "":  # a blank line ends an event
                        if data:
                            yield kind, json.loads("\n".join(data))
                        kind, data = "message", []
                    elif line.startswith(":"):
                        continue  # a comment (": still here"): Farmhand is alive, nothing happened
                    else:
                        field, _, value = line.partition(":")
                        value = value[1:] if value.startswith(" ") else value
                        if field == "event":
                            kind = value
                        elif field == "data":
                            data.append(value)
            except OSError as e:  # timed out, or the connection was cut (Farmhand restarting)
                raise FarmhandError(f"Lost Farmhand's live updates ({_reason(e)}).", "down") from None
        raise FarmhandError("Farmhand ended its live updates (it may be restarting).", "down")

    # ------------------------------------------------------------------ the plumbing

    def get(self, path: str) -> dict:
        return self.call("GET", path)

    def call(self, method: str, path: str) -> dict:
        with self._open(path, accept="application/json", timeout=self.timeout, method=method) as answer:
            return json.loads(answer.read().decode("utf-8"))

    def _open(self, path: str, accept: str, timeout: float, method: str = "GET"):
        if not self.url:
            raise FarmhandError(
                "FARMHAND_URL isn't set, so this plugin doesn't know where Farmhand is. Add the plugin on Farmhand's "
                "Plugins page, then start its container with the FARMHAND_URL and FARMHAND_TOKEN it shows you.",
                "setup",
            )
        if not self.token:
            raise FarmhandError(
                "FARMHAND_TOKEN isn't set. Add the plugin on Farmhand's Plugins page (or make it a new token there), "
                "then start its container with the FARMHAND_TOKEN it shows you.",
                "setup",
            )
        request = urllib.request.Request(
            self.url + path, headers={"Authorization": f"Bearer {self.token}", "Accept": accept}, method=method,
            data=b"" if method == "POST" else None,
        )
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as e:  # Farmhand answered, but not with 2xx
            raise _refusal(e) from None
        except (urllib.error.URLError, OSError) as e:  # nothing answered
            raise FarmhandError(f"Can't reach Farmhand at {self.url} ({_reason(e)}).", "down") from None


def _refusal(e: urllib.error.HTTPError) -> FarmhandError:
    """Farmhand's "no" (401, 403, 429...), in words for the operator."""
    detail = _detail(e)
    if e.code == 401:
        words = (
            "Farmhand refused this plugin's token: make a new one on Farmhand's Plugins page, set it as FARMHAND_TOKEN "
            "and restart this plugin's container."
        )
        return FarmhandError(f"{words} (Farmhand said: {detail})", "refused", short=words)
    if e.code == 403:
        return FarmhandError(f"Farmhand won't let this plugin read that. {detail}", "forbidden")
    if e.code == 429:
        try:
            wait = float(e.headers.get("Retry-After", "5"))
        except ValueError:
            wait = 5.0
        return FarmhandError(f"Farmhand asked this plugin to slow down; trying again in {wait:g} s. {detail}", "busy", wait)
    if e.code == 410:
        return FarmhandError(detail, "gone")
    if e.code in (502, 503, 504):
        return FarmhandError(f"Farmhand isn't ready (it answered {e.code}); it may be starting up.", "down")
    return FarmhandError(f"Farmhand answered {e.code}: {detail}", "error")


def _detail(e: urllib.error.HTTPError) -> str:
    """Farmhand's own words: the "detail" of its JSON error answer."""
    try:
        body = e.read().decode("utf-8", "replace")
    except OSError:
        return e.reason or ""
    try:
        return str(json.loads(body)["detail"])
    except (ValueError, KeyError, TypeError):
        return body.strip()[:300] or str(e.reason or "")


def _reason(e: Exception) -> str:
    reason = getattr(e, "reason", None) or e
    if isinstance(reason, TimeoutError) or "timed out" in str(reason):
        return "it didn't answer in time"
    if isinstance(reason, ConnectionRefusedError):
        return "nothing is listening there; is Farmhand running?"
    return str(reason) or type(reason).__name__
