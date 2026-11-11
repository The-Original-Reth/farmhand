"""
The Stream plugin's web server: its page (shown inside Farmhand at /plugins/stream/), the Stream page's API under
/api/stream (routes.py), and what Farmhand asks of every plugin (/manifest, /health).

Besides the stream itself, the page reads only what the plugin hands it: the farm's printers and cameras (from
Farmhand's /cameras, through the plugin), each printer's print, and a camera's latest picture for the preview (from
its feeder while live, else from the camera's snapshot address). The page never talks to Farmhand or the cameras
itself, and nothing here ever answers the stream key, the Google client secret or the YouTube sign-in.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import farm, layouts, live_stream, migrate
from .live_stream.sources import known
from .errors import answer_errors
from .routes import get_db, router
from .store import Session

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"  # the page, built by `npm run build` in ../page (the Dockerfile does it)
MANIFEST = Path("/farmhand-plugin.json") if Path("/farmhand-plugin.json").is_file() else HERE.parent / "farmhand-plugin.json"
FARM_SECONDS = 10  # the farm's cameras, as the page asks for them, are asked of Farmhand at most this often
SNAPSHOT_TIMEOUT = 4

app = FastAPI(title="Farmhand Stream plugin", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)

_farm_lock = threading.Lock()
_farm_kept: dict = {"at": 0.0, "answer": None}


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


# ------------------------------------------------------------------ the farm, for the page


def _farm(db: Session) -> dict:
    with _farm_lock:
        if _farm_kept["answer"] is not None and time.monotonic() - _farm_kept["at"] < FARM_SECONDS:
            return _farm_kept["answer"]
    known, error = farm.cameras(db)
    printers, cameras = [], {}
    for pid, p in sorted(known.items(), key=lambda kv: (kv[1].get("name") or "").lower()):
        printers.append({"id": int(pid), "name": p.get("name"), "decommissioned": False})
        cameras[pid] = {
            "error": p.get("error"),
            "webcams": [{
                "name": c.get("name"), "rotation": c.get("rotation") or 0, "flip_horizontal": bool(c.get("flip_horizontal")),
                "flip_vertical": bool(c.get("flip_vertical")), "aspect_ratio": c.get("aspect_ratio"), "target_fps": c.get("target_fps"),
                "error": c.get("error"),
            } for c in p.get("cameras") or []],
        }
    answer = {"printers": printers, "cameras": cameras, "farmhand_error": error}
    with _farm_lock:
        _farm_kept.update(at=time.monotonic(), answer=answer)
    return answer


@app.get("/api/farm")
def farm_page(db: Session = Depends(get_db)):
    """{printers: [{id, name}], cameras: {printer id: {webcams: [{name, rotation, flips, aspect_ratio, error}], error}},
    farmhand_error: why Farmhand couldn't be asked now (what was last heard is shown), or null}."""
    return _farm(db)


@app.get("/api/printers/{printer_id}/progress")
def print_progress(printer_id: int):
    """The print under way {state, progress, file, error}; {error} when Farmhand couldn't be asked."""
    got = farm.print_of(printer_id)
    if got is None:
        problem = farm.problem()
        return {"state": None, "progress": None, "file": None, "error": problem.message if problem else "Farmhand didn't answer."}
    return got


@app.get("/api/cameras/{printer_id}/{name}/picture")
def camera_picture(printer_id: int, name: str, db: Session = Depends(get_db)):
    """A camera's latest picture for the page's preview: its feeder's while live, else its snapshot address's. 404 when
    there's none to give (an RTSP camera with no snapshot address, before going live)."""
    frame = live_stream.stream.latest_frame(f"{printer_id}:{name}")
    if frame is None:
        printer = (known(db) or {}).get(str(printer_id)) or {}
        cam = next((c for c in printer.get("cameras") or [] if c.get("name") == name), None)
        url = cam and cam.get("snapshot_url")
        if not url:
            raise HTTPException(status_code=404, detail="No picture from this camera until the stream is live.")
        try:
            with urllib.request.urlopen(url, timeout=SNAPSHOT_TIMEOUT) as r:
                frame = r.read(8 * 1024 * 1024)
        except OSError as e:
            raise HTTPException(status_code=502, detail=f"The camera didn't give a picture ({e}).") from None
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ saved layouts, and the move from Farmhand


@app.get("/api/layouts")
def get_layouts(db: Session = Depends(get_db)):
    return {"layouts": layouts.layouts(db)}


@app.put("/api/layouts")
def put_layouts(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Keep these as the saved layouts: {layouts: [...]}."""
    with answer_errors():
        return {"layouts": layouts.save(db, payload.get("layouts"))}


@app.get("/api/migrate")
def migration_state(db: Session = Depends(get_db)):
    """{done: {at, stream_folder} | null, own_settings}: whether Farmhand's Stream page set-up was brought over."""
    return migrate.state(db)


@app.post("/api/migrate")
def migrate_now(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    """Bring Farmhand's Stream page set-up over now (once; over settings made here only with replace: true)."""
    with answer_errors():
        return migrate.run(db, replace=bool((payload or {}).get("replace")))


# ------------------------------------------------------------------ the page


@app.get("/", include_in_schema=False)
def index():
    page = WEB / "index.html"
    if not page.is_file():
        return PlainTextResponse("The Stream plugin's page isn't built: run npm run build in plugins/stream/page.", status_code=503)
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


if (WEB / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")
