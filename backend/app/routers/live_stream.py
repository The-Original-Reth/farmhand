from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import database
from ..database import get_db
from ..errors import answer_errors
from .. import storage
from ..schemas.live_stream import MediaLocationIn, SlideshowIn, SlideshowOrderIn, StreamSettingsIn, YouTubeClientIn, YouTubeSignOutIn
from ..services import config_service, live_stream, stream_media, youtube_live
from .common import require_confirm

# The Stream page: printers' cameras sent live to YouTube by Farmhand itself (see services/live_stream/),
# and the YouTube broadcast, made and changed through YouTube's API (live_stream/broadcast.py). The stream
# key, the Google client secret and the YouTube sign-in go in and never come back out: answers only say they're there.
router = APIRouter(prefix="/stream", tags=["stream"])

# Changing one of these while live means the picture (or the sound) changes, so the stream starts again
PICTURE = ("destination", "cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "resolution", "border_color",
           "background", "font", "color", "key_set")
MUSIC = ("music", "music_volume", "music_shuffle")  # these the music follows while live, without starting it again


def _restart_if_live(db: Session) -> None:
    if live_stream.stream.status()["live"]:
        live_stream.stream.go_live(db, database.SessionLocal)


@router.get("")
def stream_page(db: Session = Depends(get_db)):
    """{settings, media, status, destinations, resolutions, youtube}: see services/live_stream.page. Also moves a YouTube
    sign-in along."""
    return live_stream.page(db)


@router.put("")
def save_settings(payload: StreamSettingsIn, db: Session = Depends(get_db)):
    """
    Save the stream's settings. While live: a change to the picture starts the stream again with it; a new title,
    description or YouTube setting is set on the YouTube broadcast straight away; turning the stream off (enabled: false) stops it.
    """
    with answer_errors():
        before = live_stream.settings(db)
        after = live_stream.save(
            db, destination=payload.destination, chosen=payload.cameras, show_status=payload.show_status, layout=payload.layout,
            seconds_all=payload.seconds_all, seconds_each=payload.seconds_each, resolution=payload.resolution,
            border_color=payload.border_color, background=payload.background, font=payload.font, color=payload.color, enabled=payload.enabled, cols=payload.cols, rows=payload.rows, cells=payload.cells,
            title=payload.title, description=payload.description,
            music=payload.music, music_volume=payload.music_volume, music_shuffle=payload.music_shuffle, delay=payload.delay, youtube=payload.youtube,
            stream_key=payload.stream_key, clear_key=payload.clear_key,
        )
        live = live_stream.stream.status()["live"]
        if live and not after["enabled"]:  # turned off: nothing streams
            live_stream.stream.stop()
        elif live and (any(before[k] != after[k] for k in PICTURE) or payload.stream_key):
            _restart_if_live(db)
        elif live and any(before[k] != after[k] for k in MUSIC):
            live_stream.stream.music_settings(after)
        elif (live and after["destination"] == "youtube"
              and (before["title"], before["description"], before["youtube"]) != (after["title"], after["description"], after["youtube"])):
            text_changed = (before["title"], before["description"]) != (after["title"], after["description"])
            live_stream.stream.send_to_youtube(db, after, text_changed=text_changed)
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
    def on_it(c) -> bool:  # (its own picture, or one of its more pictures, a slideshow screen's too)
        layers = [*(c.get("layers") or []), *(x for ls in (c.get("slide_layers") or {}).values() for x in ls)]
        return c.get("image") == image or any(x.get("type") == "picture" and x.get("image") == image for x in layers)

    for c in live_stream.settings(db)["cells"]:
        if c and "camera" not in c and ((slideshow and c.get("slideshow") == slideshow) or (image and on_it(c))):
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


@router.put("/slideshows/{name}")
def rename_slideshow(name: str, payload: SlideshowIn, db: Session = Depends(get_db)):
    """Rename a slideshow: its folder in the stream folder, and every square showing it (on the page and in saved
    layouts) follows. 422 for a name another slideshow has. While live and it's shown, the stream starts again."""
    new = _media(lambda: stream_media.rename_slideshow(db, name, payload.name))
    if new != name and live_stream.rename_slideshow(db, name, new):
        _restart_if_used(db, new)
    return live_stream.page(db)


@router.post("/slideshows/{name}/blanks", status_code=201)
def add_blank(name: str, db: Session = Depends(get_db)):
    """A blank screen at the end of a slideshow (its colour and the words written on it). Deleted as its pictures are."""
    _media(lambda: stream_media.add_blank(db, name))
    _restart_if_used(db, name)
    return live_stream.page(db)


@router.put("/slideshows/{name}/order")
def order_slideshow(name: str, payload: SlideshowOrderIn, db: Session = Depends(get_db)):
    """Put a slideshow's pictures in the order chosen (kept in its folder). While live and it's shown, the stream starts again."""
    _media(lambda: stream_media.set_order(db, name, payload.order))
    _restart_if_used(db, name)
    return live_stream.page(db)


@router.delete("/slideshows/{name}")
def delete_slideshow(name: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Delete a slideshow: its pictures, then its folder (left when it holds anything else). Squares keep their colour."""
    require_confirm(confirm)
    _media(lambda: stream_media.remove_slideshow(db, name))
    _restart_if_used(db, name)
    return live_stream.page(db)


@router.post("/scan")
def scan_folder(db: Session = Depends(get_db)):
    """Read the stream folder again (pictures copied in, or taken out, by hand): it isn't read every time the page looks."""
    stream_media.media(db, scan=True)
    return live_stream.page(db)


@router.get("/fonts/{key}")
def get_font(key: str):
    """A font a square's words can be written in, for the page to show them as the stream does. 404 when the server
    doesn't have it (the stream then writes in its own font)."""
    path = live_stream.font_file(key)
    if key not in live_stream.FONTS or path == live_stream.FONT and key != "dejavu-sans":
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


# ------------------------------------------------------------------ the music: MP3s in the stream folder's music/
# Tracks added while live join the music's next round; it isn't stopped for them.


@router.post("/music/{action}")
def music_control(action: str, db: Session = Depends(get_db)):
    """The music going out while live: play, pause, next (the next track) or back (the track playing from its start,
    or in its first 3 seconds the one before). 422 when not live, or the music is off."""
    if action not in ("play", "pause", "next", "back"):
        raise HTTPException(status_code=404, detail="Not Found")
    with answer_errors():
        live_stream.stream.music_control(action)
    return live_stream.page(db)


@router.get("/music/{name}")
def get_track(name: str, db: Session = Depends(get_db)):
    """A track, for the page to play it."""
    path = _media(lambda: stream_media.track_path(db, name))
    return FileResponse(path, media_type=stream_media.TRACK_TYPES[path.suffix.lower()], headers={"Cache-Control": "no-cache"})


@router.post("/music", status_code=201)
async def add_tracks(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """MP3s into the music (under 50 MB each; bigger ones can be copied in by hand)."""
    for file in files:
        data = await file.read(stream_media.TRACK_MAX + 1)
        _media(lambda: stream_media.add_track(db, file.filename or "", data))
    return live_stream.page(db)


@router.delete("/music/{name}")
def delete_track(name: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    require_confirm(confirm)
    _media(lambda: stream_media.remove_track(db, name))
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
    """Set the saved title, description and YouTube settings on the live broadcast now. status.title says how it went."""
    with answer_errors():
        live_stream.stream.send_to_youtube(db, live_stream.settings(db), asked=True)
    return live_stream.page(db)
