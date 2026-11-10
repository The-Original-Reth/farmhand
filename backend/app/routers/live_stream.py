from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import database
from ..database import get_db
from ..errors import answer_errors
from .. import storage
from ..schemas.live_stream import MediaLocationIn, SlideshowIn, StreamSettingsIn, YouTubeClientIn, YouTubeSignOutIn
from ..services import config_service, live_stream, stream_media, youtube_live
from .common import require_confirm

# The Stream page: printers' cameras sent live to YouTube or Twitch by Farmhand itself (see services/live_stream.py),
# and the YouTube broadcast's title and description, set through YouTube's API (services/youtube_live.py). The stream
# key, the Google client secret and the YouTube sign-in go in and never come back out: answers only say they're there.
router = APIRouter(prefix="/stream", tags=["stream"])

# Changing one of these while live means the picture changes, so the stream starts again
PICTURE = ("destination", "cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "resolution", "border_color",
           "background", "key_set")


def _restart_if_live(db: Session) -> None:
    if live_stream.stream.status()["live"]:
        live_stream.stream.go_live(db, database.SessionLocal)


def _apply_title(db: Session) -> dict:
    """Set the live broadcast's title and description now: {state, message}. ValueError when it can't be tried."""
    chosen = live_stream.settings(db)
    creds = youtube_live.credentials(db)
    if not creds:
        raise ValueError("Sign in to YouTube first.")
    if not (chosen["title"] or chosen["description"]):
        raise ValueError("Write a title or description first, and save it.")
    try:
        done = youtube_live.set_broadcast_text(creds, chosen["title"], chosen["description"])
        outcome = {"state": "done", "message": f"Title and description set on “{done['title']}”."}
    except youtube_live.YouTubeError as e:
        outcome = {"state": "failed", "message": f"The YouTube title wasn't set: {e}"}
    live_stream.stream.title_set(outcome)
    return outcome


@router.get("")
def stream_page(db: Session = Depends(get_db)):
    """{settings, media, status, destinations, resolutions, youtube}: see services/live_stream.page. Also moves a YouTube
    sign-in along."""
    return live_stream.page(db)


@router.put("")
def save_settings(payload: StreamSettingsIn, db: Session = Depends(get_db)):
    """
    Save the stream's settings. While live: a change to the picture starts the stream again with it; a new title or
    description is set on the YouTube broadcast straight away.
    """
    with answer_errors():
        before = live_stream.settings(db)
        after = live_stream.save(
            db, destination=payload.destination, chosen=payload.cameras, show_status=payload.show_status, layout=payload.layout,
            seconds_all=payload.seconds_all, seconds_each=payload.seconds_each, resolution=payload.resolution,
            border_color=payload.border_color, background=payload.background, cols=payload.cols, rows=payload.rows, cells=payload.cells,
            title=payload.title, description=payload.description,
            stream_key=payload.stream_key, clear_key=payload.clear_key,
        )
        live = live_stream.stream.status()["live"]
        if live and (any(before[k] != after[k] for k in PICTURE) or payload.stream_key):
            _restart_if_live(db)
        elif (live and after["destination"] == "youtube" and (before["title"], before["description"]) != (after["title"], after["description"])
              and youtube_live.credentials(db)):
            _apply_title(db)
    return live_stream.page(db)


@router.post("/start")
def go_live(db: Session = Depends(get_db)):
    """Go live with what's saved. 422 says why not (no key, no cameras, a camera that can't be streamed...)."""
    with answer_errors():
        live_stream.stream.go_live(db, database.SessionLocal)
    return live_stream.page(db)


@router.post("/stop")
def stop(db: Session = Depends(get_db)):
    live_stream.stream.stop()
    return live_stream.page(db)


# ------------------------------------------------------------------ the stream folder: pictures and slideshows


@router.get("/location")
def media_location(db: Session = Depends(get_db)):
    """Where the stream folder is (Settings): {path, is_default, default_path, status} (see services/stream_media.py)."""
    return stream_media.location_info(db)


@router.put("/location")
def choose_media_location(payload: MediaLocationIn, db: Session = Depends(get_db)):
    """Choose the stream folder, or go back to the default (path null). 422 says why one can't be used."""
    with answer_errors():
        out = stream_media.set_location(db, payload.path)
    config_service.mirror_quietly(db)  # the settings copy holds which folder it is
    return out


def _media(call):
    """A stream folder request: its errors as answers (503 while the folder isn't available)."""
    try:
        with answer_errors():
            return call()
    except storage.StorageUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None


def _restart_if_used(db: Session, slideshow: str | None, image: str | None = None) -> None:
    """Pictures changed: the stream starts again with them, when it's live and a square shows them."""
    for c in live_stream.settings(db)["cells"]:
        if c and "camera" not in c and ((slideshow and c.get("slideshow") == slideshow) or (image and c.get("image") == image)):
            _restart_if_live(db)
            return


@router.get("/pictures/{name}")
def get_picture(name: str, db: Session = Depends(get_db)):
    data, kind = _media(lambda: stream_media.picture(db, None, name))
    return Response(content=data, media_type=kind, headers={"Cache-Control": "no-cache"})


@router.post("/pictures", status_code=201)
async def add_pictures(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """Pictures (PNG, JPEG or WebP, under 10 MB each) into the stream folder's images. Answers the page."""
    for file in files:
        data = await file.read(stream_media.PICTURE_MAX + 1)
        _media(lambda: stream_media.add_picture(db, None, file.filename or "", data))
    return live_stream.page(db)


@router.delete("/pictures/{name}")
def delete_picture(name: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Delete a picture from the stream folder. Squares showing it keep their colour and words."""
    require_confirm(confirm)
    _media(lambda: stream_media.remove_picture(db, None, name))
    _restart_if_used(db, None, name)
    return live_stream.page(db)


@router.post("/slideshows", status_code=201)
def add_slideshow(payload: SlideshowIn, db: Session = Depends(get_db)):
    """A new, empty slideshow: a folder of that name in the stream folder's slideshows. Answers the page."""
    _media(lambda: stream_media.add_slideshow(db, payload.name))
    return live_stream.page(db)


@router.delete("/slideshows/{name}")
def delete_slideshow(name: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Delete a slideshow: its pictures, then its folder (left when it holds anything else). Squares keep their colour."""
    require_confirm(confirm)
    _media(lambda: stream_media.remove_slideshow(db, name))
    _restart_if_used(db, name)
    return live_stream.page(db)


@router.get("/fonts/{key}")
def get_font(key: str):
    """A font a square's words can be written in, for the page to show them as the stream does. 404 when the server
    doesn't have it (the stream then writes in its own font)."""
    path = live_stream.font_file(key)
    if key not in live_stream.FONTS or path == live_stream.FONT and key != live_stream.DEFAULT_FONT:
        raise HTTPException(status_code=404, detail="That font isn't on this Farmhand.")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="That font isn't on this Farmhand.")
    kind = "font/otf" if path.endswith(".otf") else "font/ttf"
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "max-age=86400"})


@router.get("/slideshows/{name}/pictures/{picture}")
def get_slideshow_picture(name: str, picture: str, db: Session = Depends(get_db)):
    data, kind = _media(lambda: stream_media.picture(db, name, picture))
    return Response(content=data, media_type=kind, headers={"Cache-Control": "no-cache"})


@router.post("/slideshows/{name}/pictures", status_code=201)
async def add_slideshow_pictures(name: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """Pictures into a slideshow's folder (made when it isn't there). While live and it's shown, the stream starts again."""
    for file in files:
        data = await file.read(stream_media.PICTURE_MAX + 1)
        _media(lambda: stream_media.add_picture(db, name, file.filename or "", data))
    _restart_if_used(db, name)
    return live_stream.page(db)


@router.delete("/slideshows/{name}/pictures/{picture}")
def delete_slideshow_picture(name: str, picture: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    require_confirm(confirm)
    _media(lambda: stream_media.remove_picture(db, name, picture))
    _restart_if_used(db, name)
    return live_stream.page(db)


# ------------------------------------------------------------------ signing in to YouTube


@router.put("/youtube")
def youtube_client(payload: YouTubeClientIn, db: Session = Depends(get_db)):
    """The Google OAuth client to sign in with. A different client ID signs out."""
    with answer_errors():
        youtube_live.set_client(db, payload.client_id, payload.client_secret)
    return live_stream.page(db)


@router.post("/youtube/sign-in")
def youtube_sign_in(db: Session = Depends(get_db)):
    """Start signing in: youtube.signing_in gives the code to enter at google.com/device. GET /stream finishes it."""
    with answer_errors():
        youtube_live.start_sign_in(db)
    return live_stream.page(db)


@router.post("/youtube/sign-out")
def youtube_sign_out(payload: YouTubeSignOutIn | None = None, db: Session = Depends(get_db)):
    youtube_live.sign_out(db, forget_client=bool(payload and payload.forget_client))
    return live_stream.page(db)


@router.post("/youtube/apply")
def youtube_apply(db: Session = Depends(get_db)):
    """Set the saved title and description on the channel's live broadcast now. status.title says how it went."""
    with answer_errors():
        _apply_title(db)
    return live_stream.page(db)
