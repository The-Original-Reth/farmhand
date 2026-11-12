"""
The Stream plugin's web server: its page (shown inside Farmhand at /plugins/stream/), the Stream page's API under
/api/stream (routes.py), and what Farmhand asks of every plugin (/manifest, /health).

Besides the stream itself, the page reads only what the plugin hands it: the farm's printers and cameras (from
Farmhand's /cameras, through the plugin), each printer's print, and a camera's latest picture for the preview (from
its feeder while live, else from the camera's snapshot address, else a frame taken from its video). The page never talks to Farmhand or the cameras
itself, and nothing here ever answers the stream key, the Google client secret or the YouTube sign-in.
"""
from __future__ import annotations

import io
import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from . import farm, layouts, live_stream, migrate
from .live_stream import procs
from .live_stream.sources import followed_camera, known
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
    """A camera's latest picture for the page's preview: its feeder's while live, else its snapshot address's, else (no
    snapshot address, or one that doesn't answer, as Mainsail can still list after a camera moved to go2rtc) a frame
    taken from its video. Always turned the way Mainsail shows the camera, as the stream shows it (a feeder's frame is
    already; the others are turned here), so the page never turns it itself. 404 when there's none to give, 502 when the
    camera didn't give one."""
    frame = live_stream.stream.latest_frame(f"{printer_id}:{name}")
    if frame is None:
        printer = (known(db) or {}).get(str(printer_id)) or {}
        cam = followed_camera(name, printer.get("cameras") or [], printer.get("error"))
        if cam is None:
            raise HTTPException(status_code=404, detail="Farmhand doesn't list this camera.")
        url = cam.get("snapshot_url")
        snapshot_error = None
        if url:
            try:
                with urllib.request.urlopen(url, timeout=SNAPSHOT_TIMEOUT) as r:
                    frame = turned(r.read(8 * 1024 * 1024), cam.get("ffmpeg_filters") or [])
            except OSError as e:
                snapshot_error = f"The camera didn't give a picture ({e})."
        if frame is None:
            frame = _frame_from_video(f"{printer_id}:{cam.get('name')}", cam, snapshot_error)
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# A frame taken from a camera's video (for the preview, before going live) is shown again for this long before another
# is taken: the page asks twice a second, and each one opens a connection to the camera.
VIDEO_FRAME_SECONDS = 3
VIDEO_FRAME_TIMEOUT = 12
_frames_lock = threading.Lock()
_frames: dict[str, dict] = {}  # "printer id:camera" -> {lock, at, frame, error}


# Farmhand's turn filters (camera_streams: Mainsail's rotation, then its flips), as Pillow does them
_PIL_TURNS = {"transpose=1": Image.Transpose.ROTATE_270, "transpose=2": Image.Transpose.ROTATE_90,
              "hflip": Image.Transpose.FLIP_LEFT_RIGHT, "vflip": Image.Transpose.FLIP_TOP_BOTTOM}


def turned(jpeg: bytes, turn: list[str]) -> bytes:
    """A snapshot turned as the stream turns the camera (`turn`: its ffmpeg filters); as it was when there's nothing to
    turn, or it isn't a picture Pillow reads."""
    steps = [_PIL_TURNS[t] for t in turn if t in _PIL_TURNS]
    if not steps:
        return jpeg
    try:
        with Image.open(io.BytesIO(jpeg)) as im:
            pic = im.convert("RGB")
        for step in steps:
            pic = pic.transpose(step)
        out = io.BytesIO()
        pic.save(out, "JPEG", quality=85)
        return out.getvalue()
    except (OSError, ValueError):
        return jpeg


def take_frame(args: list[str]) -> bytes:
    """One JPEG from ffmpeg (its own command line); RuntimeError says why there's none."""
    try:
        done = subprocess.run(args, capture_output=True, timeout=VIDEO_FRAME_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise RuntimeError("the camera didn't answer in time") from None
    except OSError as e:
        raise RuntimeError(str(e)) from None
    if done.returncode != 0 or not done.stdout:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(said[-1] if said else "ffmpeg gave no picture")
    return done.stdout


def _frame_from_video(key: str, cam: dict, snapshot_error: str | None) -> bytes:
    args = cam.get("ffmpeg_input")
    ffmpeg = procs.ffmpeg_path()
    if not args or not ffmpeg:
        if snapshot_error:
            raise HTTPException(status_code=502, detail=snapshot_error)
        raise HTTPException(status_code=404, detail="No picture from this camera until the stream is live.")
    with _frames_lock:
        kept = _frames.setdefault(key, {"lock": threading.Lock(), "at": None, "frame": None, "error": None})
    with kept["lock"]:  # (the page's asks for the same camera share one connection to it)
        if kept["at"] is None or time.monotonic() - kept["at"] >= VIDEO_FRAME_SECONDS:
            try:
                turn = cam.get("ffmpeg_filters") or []
                kept.update(frame=take_frame([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *args,
                                              *(["-vf", ",".join(turn)] if turn else []),
                                              "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]), error=None)
            except RuntimeError as e:
                kept.update(frame=None, error=f"The camera didn't give a picture ({e}).")
            kept["at"] = time.monotonic()
        if kept["frame"] is None:
            raise HTTPException(status_code=502, detail=kept["error"])
        return kept["frame"]


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
