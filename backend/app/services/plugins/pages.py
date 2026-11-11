"""
A plugin's page inside Farmhand: the browser asks the web server for /plugins/<id>/..., nginx passes that to the API
as /plugins/<id>/page/..., and this passes it on to the plugin at its address, wherever it runs, and its answer back
(streamed, so server-sent events work). The address is looked up on every request, so a plugin that moved or
stopped never needs nginx changed. A plugin that's switched off, or not answering, gets a small page saying so
instead, in Farmhand's colours.

Websockets aren't passed on (docs/plugins.md says to use server-sent events or asking now and then).
"""
from __future__ import annotations

import html
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from . import remote

SCRIPT = Path(__file__).with_name("farmhand-plugin.js")  # served at /plugins/farmhand-plugin.js

# Not passed on either way: they're about one connection, not the page
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "trailers",
    "transfer-encoding", "upgrade", "host", "content-length",
}
CONNECT_TIMEOUT = 5.0


def prefix_of(plugin_id: str) -> str:
    """Where the browser sees the plugin's pages."""
    return f"/plugins/{plugin_id}"


async def forward(request: Request, plugin_id: str, address: str, path: str, colors: dict) -> Response:
    """The plugin's answer to this request, passed on; a page saying it isn't running when it can't be reached."""
    prefix = prefix_of(plugin_id)
    url = f"{address}/{path}" + (f"?{request.url.query}" if request.url.query else "")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    headers["X-Forwarded-Prefix"] = prefix
    headers["X-Forwarded-Host"] = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    if request.client:
        headers["X-Forwarded-For"] = ", ".join(filter(None, [request.headers.get("x-forwarded-for"), request.client.host]))
    body = await request.body()
    client = httpx.AsyncClient(
        transport=remote.transport, follow_redirects=False,
        timeout=httpx.Timeout(CONNECT_TIMEOUT, read=None),  # read=None: a page's event stream stays open
    )
    try:
        answer = await client.send(client.build_request(request.method, url, headers=headers, content=body), stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        return message_page(colors, "This plugin isn't running", remote.unreachable(address, e), 502)

    out_headers = [(k, v) for k, v in answer.headers.multi_items() if k.lower() not in HOP_BY_HOP]
    out_headers = [(k, _moved(v, address, prefix) if k.lower() == "location" else v) for k, v in out_headers]

    async def close():
        await answer.aclose()
        await client.aclose()

    # (an answer read already, as a stand-in plugin's is, is passed on as it was read)
    chunks = _once(answer.content) if answer.is_stream_consumed else answer.aiter_raw()
    response = StreamingResponse(chunks, status_code=answer.status_code, background=BackgroundTask(close))
    response.raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in out_headers]
    return response


async def _once(content: bytes):
    yield content


def _moved(location: str, address: str, prefix: str) -> str:
    """A redirect the plugin gives, pointed at its pages inside Farmhand rather than at the plugin itself."""
    if location.startswith(address + "/") or location == address:
        return prefix + (location[len(address):] or "/")
    if location.startswith("/") and not location.startswith("//") and not location.startswith(prefix + "/"):
        return prefix + location
    return location


def message_page(colors: dict, title: str, text: str, status: int) -> HTMLResponse:
    """A small page in Farmhand's colours, shown where the plugin's page would be."""
    bg, panel, border = colors.get("bg", "#1B1D1E"), colors.get("panel", "#232527"), colors.get("border", "#3D4042")
    heading, muted = colors.get("heading", "#FFFFFF"), colors.get("textMuted", "#CBCED0")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{margin:0;font-family:system-ui,sans-serif;background:{bg};color:{muted};display:flex;align-items:center;
justify-content:center;min-height:100vh}}div{{max-width:560px;padding:24px 28px;border:1px solid {border};border-radius:4px;
background:{panel};line-height:1.5}}h1{{font-size:17px;color:{heading};margin:0 0 8px}}p{{margin:0;font-size:14px}}</style>
</head><body><div><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p></div></body></html>"""
    return HTMLResponse(page, status_code=status, headers={"Cache-Control": "no-store"})


def script() -> Response:
    return Response(SCRIPT.read_text(encoding="utf-8"), media_type="text/javascript", headers={"Cache-Control": "no-cache"})
