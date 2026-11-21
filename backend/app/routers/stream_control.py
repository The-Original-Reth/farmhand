"""
Stream control, Farmhand's built-in plugin (services/stream_control): the one stream designed here, its pictures and
music in the stream folder, its saved layouts, the stream plugins started and stopped from here, and the schedule.
Every route answers 404 while Stream control is switched off (the Plugins page switches it: PATCH /plugins/stream-control).
Changes answer the whole page (GET /stream-control) except where said.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import storage
from ..database import get_db
from ..errors import answer_errors
from ..services import network_shares_service, stream_control
from ..services.stream_control import copy_layout, design, fonts, layouts, media, music_sources, schedule, streams
from ..services.stream_control.page import page
from .common import require_confirm, stream_picture_response, stream_track_response


def switched_on(db: Session = Depends(get_db)) -> None:
    with answer_errors():
        stream_control.require_on(db)


router = APIRouter(prefix="/stream-control", tags=["stream control"], dependencies=[Depends(switched_on)])


class SlideshowIn(BaseModel):
    name: str = Field(..., max_length=200)  # a slideshow's (new) name: its folder's in the stream folder's slideshows


class SlideshowOrderIn(BaseModel):
    order: list[str] = Field(..., max_length=2000)  # its pictures' file names (and blank screens) in the order chosen


@router.get("")
def stream_control_page(db: Session = Depends(get_db)):
    return page(db)


@router.put("")
def save_design(body: dict = Body(...), db: Session = Depends(get_db)):
    """Save the stream's design: what's sent changes, the rest stays (see design.save). The stream plugins following
    it pick the change up themselves (its revision goes up by one). The stream folder is read again too, so a picture
    or track replaced there by hand under its own name gets a new stamp, and the plugins copy it again."""
    with answer_errors():
        design.save(db, body)
    media.forget()
    return page(db)


# ------------------------------------------------------------------ the stream plugins


def _streams_answer(listed: list[dict]) -> dict:
    """{streams, happened}: the stream plugins as listed, with what the schedule did lately."""
    return {"streams": listed, "happened": schedule.happened()}


@router.get("/streams")
def stream_plugins(db: Session = Depends(get_db)):
    """Each stream plugin and how its stream is doing (the page asks every few seconds)."""
    return _streams_answer(streams.listed(db))


class ChosenIn(BaseModel):
    chosen: list[str] = Field(..., max_length=100)  # the stream plugins' ids to bring in; the others are left out


@router.put("/streams")
def choose_streams(body: ChosenIn, db: Session = Depends(get_db)):
    """Which stream plugins Stream control brings in: {streams, happened}. One left out keeps its own layout and isn't
    started or stopped from here. In the settings copy."""
    with answer_errors():
        return _streams_answer(streams.choose(db, body.chosen))


@router.post("/streams/{plugin_id}/copy-layout")
def copy_layout_of(plugin_id: str, db: Session = Depends(get_db)):
    """Copy layout: this stream plugin's own layout made Stream control's (every stream brought in then shows it), with
    the pictures and slideshows it shows copied into the stream folder. The page, with `copied` (what was copied) and
    `problems` (what wasn't, in plain words). **422** when it can't be asked or has no layout; **404** no such plugin."""
    with answer_errors():
        done = copy_layout.copy_from(db, plugin_id)
    return {**page(db), "copied": done["copied"], "problems": done["problems"]}


@router.post("/streams/{plugin_id}/{action}")
def start_or_stop(plugin_id: str, action: str, db: Session = Depends(get_db)):
    """Start or stop one stream plugin's stream: its entry as it answered (`error` says why it didn't)."""
    if action not in ("start", "stop"):
        raise HTTPException(status_code=404, detail="Not Found")
    with answer_errors():
        return streams.start_or_stop(db, plugin_id, action)


@router.post("/start-all")
def start_all(db: Session = Depends(get_db)):
    """Every switched-on stream plugin told to go live: {streams: [each one's entry as it answered]}."""
    return {"streams": streams.all_of(db, "start")}


@router.post("/stop-all")
def stop_all(db: Session = Depends(get_db)):
    return {"streams": streams.all_of(db, "stop")}


@router.post("/music/{action}")
def music_control(action: str, db: Session = Depends(get_db)):
    """Back, Play, Pause or Next on the music going out on each live stream brought into Stream control (each stream
    plugin's own POST /api/stream/music/<action>): {streams, happened}, as afterwards (each one's `music`: {on, playing,
    track, at}). **422** when no stream could do it (none live, or its music is off), with what each said."""
    if action not in streams.MUSIC_ACTIONS:
        raise HTTPException(status_code=404, detail="Not Found")
    with answer_errors():
        return _streams_answer(streams.music(db, action))


@router.put("/schedule")
def save_schedule(body: dict = Body(...), db: Session = Depends(get_db)):
    """{on, entries: [{days: [0 (Monday) to 6], start: "HH:MM" | null, stop: "HH:MM" | null, streams: "all" | [ids]}]}."""
    with answer_errors():
        schedule.save(db, body)
    return page(db, with_streams=False)


@router.put("/layouts")
def save_layouts(body: list = Body(...), db: Session = Depends(get_db)):
    """The saved layouts, all of them (each named; anything that can't be one is left out)."""
    with answer_errors():
        layouts.save(db, body)
    return page(db, with_streams=False)


# ------------------------------------------------------------------ the stream folder: pictures, slideshows, music

def _media(call):
    """A stream folder call, its NotFound and ValueError answered as 404 and 422 (and the folder away as 503)."""
    with answer_errors():
        return call()


async def _take_in(files: list[UploadFile], most: int, add) -> None:
    """Each uploaded file, read up to one byte past `most` (so one too big is refused as such), handed to
    add(file name, data) in turn."""
    for file in files:
        data = await file.read(most + 1)
        _media(lambda: add(file.filename or "", data))


@router.post("/scan")
def scan_folder(db: Session = Depends(get_db)):
    """Read the stream folder again (pictures or music copied in, or taken out, by hand)."""
    media.media(db, scan=True)
    return page(db, with_streams=False)


@router.post("/reconnect")
def reconnect_nas(db: Session = Depends(get_db)):
    """Reconnect NAS: connect the network share the stream folder (beside the STL folder) is on again, after the NAS
    was off, then read the folder again. A share still mounted but not answering is disconnected first. 422 says why
    it couldn't be connected."""
    with answer_errors():
        network_shares_service.reconnect_holding(db, storage.effective_root("stl"))
    media.media(db, scan=True)
    return page(db, with_streams=False)


@router.get("/pictures/{name}")
def get_picture(name: str, db: Session = Depends(get_db)):
    return _media(lambda: stream_picture_response(media.picture_path(db, None, name)))


@router.post("/pictures", status_code=201)
async def add_pictures(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """Pictures (PNG, JPEG, WebP or SVG, under 10 MB each) into the stream folder's images."""
    await _take_in(files, media.PICTURE_MAX, lambda filename, data: media.add_picture(db, None, filename, data))
    return page(db, with_streams=False)


@router.delete("/pictures/{name}")
def delete_picture(name: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Delete a picture from the stream folder. Squares showing it keep their colour and words."""
    require_confirm(confirm)
    _media(lambda: media.remove_picture(db, None, name))
    return page(db, with_streams=False)


@router.post("/slideshows", status_code=201)
def add_slideshow(body: SlideshowIn, db: Session = Depends(get_db)):
    _media(lambda: media.add_slideshow(db, body.name))
    return page(db, with_streams=False)


@router.put("/slideshows/{name}")
def rename_slideshow(name: str, body: SlideshowIn, db: Session = Depends(get_db)):
    """Rename a slideshow: its folder, and every square showing it (in the design and saved layouts) follows."""
    _media(lambda: design.rename_slideshow_folder(db, name, body.name))
    return page(db, with_streams=False)


@router.delete("/slideshows/{name}")
def delete_slideshow(name: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Delete a slideshow: its pictures, then its folder (left when it holds anything else)."""
    require_confirm(confirm)
    _media(lambda: media.remove_slideshow(db, name))
    return page(db, with_streams=False)


@router.post("/slideshows/{name}/blanks", status_code=201)
def add_blank(name: str, db: Session = Depends(get_db)):
    """A blank screen at the end of a slideshow (its colour and the words written on it)."""
    _media(lambda: media.add_blank(db, name))
    return page(db, with_streams=False)


@router.put("/slideshows/{name}/order")
def order_slideshow(name: str, body: SlideshowOrderIn, db: Session = Depends(get_db)):
    _media(lambda: media.set_order(db, name, body.order))
    return page(db, with_streams=False)


@router.get("/slideshows/{name}/pictures/{picture}")
def get_slideshow_picture(name: str, picture: str, db: Session = Depends(get_db)):
    return _media(lambda: stream_picture_response(media.picture_path(db, name, picture)))


@router.post("/slideshows/{name}/pictures", status_code=201)
async def add_slideshow_pictures(name: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    await _take_in(files, media.PICTURE_MAX, lambda filename, data: media.add_picture(db, name, filename, data))
    return page(db, with_streams=False)


@router.delete("/slideshows/{name}/pictures/{picture}")
def delete_slideshow_picture(name: str, picture: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    require_confirm(confirm)
    _media(lambda: media.remove_picture(db, name, picture))
    return page(db, with_streams=False)


@router.get("/music/{name}")
def get_track(name: str, db: Session = Depends(get_db)):
    """A track of the stream's music, from whichever chosen folder has it (a stream plugin's passed on, not copied)."""
    return _media(lambda: stream_track_response(music_sources.find(db, name)))


@router.post("/music", status_code=201)
async def add_tracks(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """MP3s into the stream folder's music (under 50 MB each; bigger ones can be copied in by hand)."""
    await _take_in(files, media.TRACK_MAX, lambda filename, data: media.add_track(db, filename, data))
    return page(db, with_streams=False)


@router.delete("/music/{name}")
def delete_track(name: str, confirm: bool = Query(False), db: Session = Depends(get_db)):
    require_confirm(confirm)
    _media(lambda: media.remove_track(db, name))
    return page(db, with_streams=False)


@router.get("/fonts/{key}")
def get_font(key: str):
    """A font the stream's words can be written in, for the page to show them as the stream will (404 when this
    Farmhand doesn't have it: the page uses its kind of font)."""
    path = fonts.font_file(key)
    if path is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(path, media_type="font/otf" if path.endswith(".otf") else "font/ttf",
                        headers={"Cache-Control": "max-age=86400"})
