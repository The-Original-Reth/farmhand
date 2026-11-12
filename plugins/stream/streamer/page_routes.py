"""
What the Stream page reads besides the stream itself, all through the plugin (the page never talks to Farmhand or the
cameras): the farm's printers and cameras (from Farmhand's /cameras), each printer's print, a camera's latest picture
for the preview, the saved layouts, and the one-off move from Farmhand's own Stream page.
"""
from __future__ import annotations

import io
import subprocess
import threading
import time
import urllib.request

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from PIL import Image

from . import farm, layouts, live_stream, migrate
from .errors import answer_errors
from .live_stream import procs
from .live_stream.sources import followed_camera, known
from .routes import get_db
from .store import Store

FARM_SECONDS = 10  # the farm's cameras, as the page asks for them, are asked of Farmhand at most this often
SNAPSHOT_TIMEOUT = 4

router = APIRouter()

_farm_lock = threading.Lock()
_farm_kept: dict = {"at": 0.0, "answer": None}


# ------------------------------------------------------------------ the farm, for the page


def _farm(db: Store) -> dict:
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


@router.get("/api/farm")
def farm_page(db: Store = Depends(get_db)):
    """{printers: [{id, name}], cameras: {printer id: {webcams: [{name, rotation, flips, aspect_ratio, error}], error}},
    farmhand_error: why Farmhand couldn't be asked now (what was last heard is shown), or null}."""
    return _farm(db)


@router.get("/api/printers/{printer_id}/progress")
def print_progress(printer_id: int):
    """The print under way {state, progress, file, error}; {error} when Farmhand couldn't be asked."""
    got = farm.print_of(printer_id)
    if got is None:
        problem = farm.problem()
        return {"state": None, "progress": None, "file": None, "error": problem.message if problem else "Farmhand didn't answer."}
    return got


@router.get("/api/cameras/{printer_id}/{name}/picture")
def camera_picture(printer_id: int, name: str, db: Store = Depends(get_db)):
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


@router.get("/api/layouts")
def get_layouts(db: Store = Depends(get_db)):
    return {"layouts": layouts.layouts(db)}


@router.put("/api/layouts")
def put_layouts(payload: dict = Body(...), db: Store = Depends(get_db)):
    """Keep these as the saved layouts: {layouts: [...]}."""
    with answer_errors():
        return {"layouts": layouts.save(db, payload.get("layouts"))}


@router.get("/api/migrate")
def migration_state(db: Store = Depends(get_db)):
    """{done: {at, stream_folder} | null, own_settings}: whether Farmhand's Stream page set-up was brought over."""
    return migrate.state(db)


@router.post("/api/migrate")
def migrate_now(payload: dict = Body(default={}), db: Store = Depends(get_db)):
    """Bring Farmhand's Stream page set-up over now (once; over settings made here only with replace: true)."""
    with answer_errors():
        return migrate.run(db, replace=bool((payload or {}).get("replace")))
