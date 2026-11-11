"""
Google's sign-in for devices and the bits of the YouTube Data API Farmhand uses, for the stream tests: `google`
(conftest) puts FakeGoogle in place of youtube_live's transport. `signed_in(api, google)` signs the test's Farmhand in.
"""
from __future__ import annotations

import httpx

from app.services import youtube_live

CLIENT_ID = "1234-abcd.apps.googleusercontent.com"
SECRET = "GOCSPX-secret_value"


class FakeGoogle:
    """Google's sign-in for devices and the bits of the YouTube Data API Farmhand uses."""

    def __init__(self):
        self.entered = False  # the code typed in at google.com/device
        self.denied = False
        self.broadcasts: list[dict] = []
        self.videos: dict[str, dict] = {}
        self.revoked: list[str] = []
        self.requests: list[httpx.Request] = []
        self.streams: dict[str, dict] = {}  # liveStreams made, by id
        self.made: dict[str, dict] = {}  # liveBroadcasts made, by id ({snippet, status, contentDetails, bound})
        self.ended: list[str] = []
        self.deleted: list[str] = []
        self.refuse_broadcast = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        form = dict(httpx.QueryParams(request.content.decode())) if request.method == "POST" else {}
        if url == youtube_live.DEVICE_URL:
            if form.get("client_id") != CLIENT_ID:
                return httpx.Response(401, json={"error": "invalid_client", "error_description": "The OAuth client was not found."})
            return httpx.Response(200, json={"device_code": "dev-1", "user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device",
                                             "expires_in": 1800, "interval": 0})
        if url == youtube_live.TOKEN_URL:
            if form.get("grant_type") == youtube_live.DEVICE_GRANT:
                if self.denied:
                    return httpx.Response(403, json={"error": "access_denied"})
                if not self.entered:
                    return httpx.Response(428, json={"error": "authorization_pending"})
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3599})
            if form.get("refresh_token") == "rt-1" and form.get("client_secret") == SECRET:
                return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3599})
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
        if url.startswith(youtube_live.REVOKE_URL):
            self.revoked.append(form.get("token"))
            return httpx.Response(200, json={})
        if request.headers.get("authorization") not in ("Bearer at-1", "Bearer at-2"):
            return httpx.Response(401, json={"error": {"code": 401, "message": "Invalid Credentials"}})
        path = request.url.path.removeprefix("/youtube/v3")
        if path == "/channels":
            return httpx.Response(200, json={"items": [{"snippet": {"title": "3D Printing Elves"}}]})
        import json

        params = request.url.params
        body = json.loads(request.content) if request.content and request.method in ("POST", "PUT") else None
        if path == "/liveStreams" and request.method == "GET":
            return httpx.Response(200, json={"items": [self.streams[params["id"]]] if params.get("id") in self.streams else []})
        if path == "/liveStreams" and request.method == "POST":
            sid = f"stream-{len(self.streams) + 1}"
            self.streams[sid] = {"id": sid, **body, "cdn": {**body["cdn"], "ingestionInfo": {
                "streamName": f"key-{sid}", "rtmpsIngestionAddress": "rtmps://a.rtmps.youtube.com/live2"}},
                "status": {"healthStatus": {"status": "good", "configurationIssues": [
                    {"severity": "warning", "description": "Use a higher bitrate."}, {"severity": "info", "description": "fine"}]}}}
            return httpx.Response(200, json=self.streams[sid])
        if path == "/liveBroadcasts" and request.method == "POST":
            if self.refuse_broadcast:
                return httpx.Response(403, json={"error": {"code": 403, "message": "The user is not enabled for live streaming."}})
            bid = f"bc-{len(self.made) + 1}"
            self.made[bid] = {**body, "bound": None, "life": "ready"}
            self.videos[bid] = dict(body["snippet"])
            return httpx.Response(200, json={"id": bid, **body})
        if path == "/liveBroadcasts/bind":
            self.made[params["id"]]["bound"] = params["streamId"]
            return httpx.Response(200, json={"id": params["id"]})
        if path == "/liveBroadcasts/transition":
            if self.made[params["id"]]["life"] != "live":
                return httpx.Response(403, json={"error": {"code": 403, "message": "Invalid transition"}})
            self.made[params["id"]]["life"] = "complete"
            self.ended.append(params["id"])
            return httpx.Response(200, json={})
        if path == "/liveBroadcasts" and request.method == "DELETE":
            self.deleted.append(params["id"])
            self.made.pop(params["id"], None)
            return httpx.Response(204)
        if path == "/liveBroadcasts" and params.get("id"):
            b = self.made.get(params["id"])
            return httpx.Response(200, json={"items": [{"id": params["id"], "status": {"lifeCycleStatus": b["life"]}}] if b else []})
        if path == "/liveBroadcasts":
            return httpx.Response(200, json={"items": self.broadcasts})
        if path == "/videos" and request.method == "GET" and params.get("part") == "liveStreamingDetails":
            return httpx.Response(200, json={"items": [{"id": params["id"], "liveStreamingDetails": {"concurrentViewers": "7"}}]})
        if path == "/videos" and request.method == "GET":
            vid = request.url.params["id"]
            return httpx.Response(200, json={"items": [{"id": vid, "snippet": self.videos[vid]}] if vid in self.videos else []})
        if path == "/videos" and request.method == "PUT":
            self.videos[body["id"]] = body["snippet"]
            if body.get("status") and body["id"] in self.made:
                self.made[body["id"]]["status"] = body["status"]
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": {"code": 404, "message": "Not found"}})


def signed_in(api, google):
    api.put("/stream/youtube", json={"client_id": CLIENT_ID, "client_secret": SECRET})
    api.post("/stream/youtube/sign-in")
    google.entered = True
    return api.get("/stream").json()["youtube"]
