"""
A stand-in for a plugin running somewhere on the farm's network, enough of it to test Farmhand against: its /manifest,
its /health, a page, a form it takes, a redirect, and an event stream. Plug it in with
`remote.transport = httpx.MockTransport(fake.handle)` (it serves every address Farmhand asks; `fake.address` is the
one it's registered at).
"""
from __future__ import annotations

import httpx

MANIFEST = {
    "id": "hello", "name": "Hello", "version": "0.1.0", "farmhand_api": "1", "port": 8080,
    "author": "Elves", "page": {"menu": "Hello", "path": "/"},
    "permissions": ["printers:read", "farm:read"], "health": "/health",
}


class FakePlugin:
    def __init__(self, address="http://192.168.10.215:8080", manifest=None):
        self.address = address
        self.manifest = dict(manifest or MANIFEST)
        self.down = False  # True: nothing answers at its address (the container is stopped)
        self.unwell = False  # True: /health answers 503
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down or not str(request.url).startswith(self.address):
            raise httpx.ConnectError("Connection refused", request=request)
        path = str(request.url)[len(self.address):].split("?")[0] or "/"
        if path == "/manifest":
            return httpx.Response(200, json=self.manifest)
        if path == "/health":
            return httpx.Response(503, text="the camera reader is stuck") if self.unwell else httpx.Response(200, json={"ok": True})
        if path == "/":
            return httpx.Response(200, html="<h1>Hello from the plugin</h1>", headers={"X-Plugin": "hello", "Set-Cookie": "a=1"})
        if path == "/echo":
            return httpx.Response(200, json={
                "method": request.method, "query": request.url.query.decode(), "body": request.content.decode(),
                "prefix": request.headers.get("x-forwarded-prefix"),
            })
        if path == "/old":
            return httpx.Response(302, headers={"Location": f"{self.address}/new"})
        if path == "/events":
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=b"event: hi\ndata: 1\n\n")
        return httpx.Response(404, text="not here")
