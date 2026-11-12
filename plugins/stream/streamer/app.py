"""
The Stream plugin's web server: its page (shown inside Farmhand at /plugins/stream/), the Stream page's API under
/api/stream (routes.py), what else the page reads (page_routes.py), and what Farmhand asks of every plugin (/manifest,
/health).

Besides the stream itself, the page reads only what the plugin hands it: the farm's printers and cameras (from
Farmhand's /cameras, through the plugin), each printer's print, and a camera's latest picture for the preview (from
its feeder while live, else from the camera's snapshot address, else a frame taken from its video). The page never talks to Farmhand or the cameras
itself, and nothing here ever answers the stream key, the Google client secret or the YouTube sign-in.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from . import farm, page_routes
from .routes import router

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"  # the page, built by `npm run build` in ../page (the Dockerfile does it)
MANIFEST = Path("/farmhand-plugin.json") if Path("/farmhand-plugin.json").is_file() else HERE.parent / "farmhand-plugin.json"

app = FastAPI(title="Farmhand Stream plugin", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)
app.include_router(page_routes.router)


def read_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@app.get("/manifest")
def manifest():
    return read_manifest()


@app.get("/health")
def health():
    """Well unless Farmhand refuses this plugin (its token, or a permission), which the operator must fix on Farmhand's
    Plugins page (it shows this answer). Farmhand being down isn't the plugin being unwell: the stream carries on."""
    problem = farm.problem()
    if problem and problem.kind in ("setup", "refused", "forbidden"):
        return PlainTextResponse(problem.short, status_code=503)
    return PlainTextResponse("ok")


# ------------------------------------------------------------------ the page


@app.get("/", include_in_schema=False)
def index():
    page = WEB / "index.html"
    if not page.is_file():
        return PlainTextResponse("The Stream plugin's page isn't built: run npm run build in plugins/stream/page.", status_code=503)
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


if (WEB / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")
