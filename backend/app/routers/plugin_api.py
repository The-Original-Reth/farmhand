"""
The plugin API, version 1: what a plugin's container may read of Farmhand (docs/plugins.md has every shape). Each call
carries the plugin's token (Authorization: Bearer ...): none or a bad one is 401, and a call outside the permissions
the operator granted it is 403 naming the one it needs. It only reads, except a Prusa
printer's status reported by a plugin it's switched to (printers:report), and a plugin's own copy of its settings
(stream:backup). v1 only ever gains fields and endpoints.

Reached over the farm's network on the API's port (a plugin may run on another machine), never through the web
page's server (nginx doesn't pass /plugin-api/ on). Besides the token: a plugin set to "only accept calls from its
address" has its token refused from anywhere else (403), and each token may make RATE calls a second (429 beyond).
"""
from __future__ import annotations

import json
import math
from urllib.parse import quote
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFound
from ..services import print_progress, printer_reports, stream_control
from ..services.plugins import answers, backups, events, handover, limits, registry, remote
from ..services.plugins.manifest import API_VERSION
from ..services.stream_control import design as stream_design
from ..services.stream_control import media as stream_media
from ..services.stream_control import music_sources
from ..services.stream_control import streams as stream_streams
from .common import require_printer, stream_picture_response, stream_track_response

router = APIRouter(prefix=f"/plugin-api/v{API_VERSION}", tags=["plugin API"])

NO_TOKEN = "This needs the plugin's token, sent as \"Authorization: Bearer <token>\" (the FARMHAND_TOKEN it was given)."
BAD_TOKEN = (
    "That plugin token isn't valid: it was replaced by a new one, the plugin was removed or turned off, or it was "
    "never made here. The operator can give the plugin a new token on Farmhand's Plugins page."
)


def plugin_caller(
    request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db),
) -> registry.Caller:
    """
    The plugin making the call, known by its token: 401 without one Farmhand knows, 429 when it asks too often, 403
    from somewhere other than its address when it's set to be taken only from there.
    """
    return _caller(request, authorization, db, limited=True)


def file_caller(
    request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db),
) -> registry.Caller:
    """plugin_caller for Stream control's files: not counted against how often a plugin may ask. A stream plugin
    copies every picture the stream shows (dozens, sponsors' logos say) when it starts following, and they're only ever
    the files in Stream control's stream folder."""
    return _caller(request, authorization, db, limited=False)


def _caller(request: Request, authorization: str | None, db: Session, limited: bool) -> registry.Caller:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail=NO_TOKEN, headers={"WWW-Authenticate": "Bearer"})
    token = token.strip()
    wait = limits.allow(registry.hash_token(token)) if limited else 0
    if wait:
        raise HTTPException(
            status_code=429, headers={"Retry-After": str(max(1, math.ceil(wait)))},
            detail=f"This plugin is asking Farmhand too often (more than {limits.RATE:g} times a second). Farmhand keeps "
            "its answers a few seconds anyway, so asking less often loses nothing.",
        )
    caller = registry.caller(db, token)
    if caller is None:
        raise HTTPException(status_code=401, detail=BAD_TOKEN, headers={"WWW-Authenticate": "Bearer"})
    if caller.only_from:
        came_from = request.client.host if request.client else None
        if not remote.from_address(came_from, caller.only_from):
            raise HTTPException(
                status_code=403,
                detail=f"Farmhand takes the \"{caller.plugin_id}\" plugin's token only from its address, "
                f"{remote.host_of(caller.only_from)}, and this call came from {came_from or 'an unknown address'}. If the "
                "plugin has moved, change its address on Farmhand's Plugins page (or switch off \"Only from its "
                "address\" there).",
            )
    return caller


def needs(permission: str, limited: bool = True) -> Callable[..., registry.Caller]:
    """A dependency: the calling plugin, which must have been granted this permission (403 naming it otherwise).
    `limited`: counted against how often it may ask (all but Stream control's files)."""

    def check(caller: registry.Caller = Depends(plugin_caller if limited else file_caller)) -> registry.Caller:
        if permission not in caller.permissions:
            raise HTTPException(
                status_code=403,
                detail=f"The \"{caller.plugin_id}\" plugin hasn't been given the {permission} permission, which this "
                "needs. Add it to the plugin's manifest; the operator grants it when installing the plugin.",
            )
        return caller

    return check


@router.get("/me")
def me(caller: registry.Caller = Depends(plugin_caller)):
    """Which plugin this token is, and what it may read: a plugin's first call, to check its token works."""
    return {"plugin_id": caller.plugin_id, "permissions": sorted(caller.permissions), "api_version": API_VERSION}


@router.get("/printers", dependencies=[Depends(needs("printers:read"))])
def printers(db: Session = Depends(get_db)):
    return answers.printers(db)


@router.get("/cameras", dependencies=[Depends(needs("cameras:read"))])
def cameras(db: Session = Depends(get_db)):
    return answers.cameras_of_farm(db)


@router.get("/printers/{printer_id}/print", dependencies=[Depends(needs("prints:read"))])
def printer_print(printer_id: int, db: Session = Depends(get_db)):
    return answers.print_of(db, require_printer(db, printer_id))


@router.get("/events")
async def printer_events(request: Request, caller: registry.Caller = Depends(needs("prints:read"))):
    # The stream outlives this request's database session, so each check opens one of its own (the same database:
    # get_db, or what stands in for it in tests)
    open_db = request.app.dependency_overrides.get(get_db, get_db)

    def still_allowed() -> bool:
        session = open_db()
        try:
            return registry.still_taken(next(session), caller.token_hash, "prints:read")
        finally:
            session.close()

    return StreamingResponse(
        events.stream(still_allowed=still_allowed), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ReportedTemps(BaseModel):
    temp_nozzle: float | None = None
    target_nozzle: float | None = None
    temp_bed: float | None = None
    target_bed: float | None = None


class ReportedJob(BaseModel):
    id: int  # the printer's own job number (PrusaLink's): a new number is a new print
    state: str | None = Field(None, max_length=40)  # PRINTING, PAUSED, FINISHED, STOPPED, ERROR...
    file: str | None = Field(None, max_length=255)  # the file's name, as it should be shown
    display_name: str | None = Field(None, max_length=255)
    path: str | None = Field(None, max_length=500)  # where it is on the printer
    progress: float | None = Field(None, ge=0, le=100)
    time_printing: float | None = Field(None, ge=0)  # seconds
    time_remaining: float | None = Field(None, ge=0)  # seconds


class ReportedDialog(BaseModel):
    """A message the printer shows on its screen, waiting for someone (its state is then ATTENTION, say)."""

    code: str | None = Field(None, max_length=40)  # Prusa's own code for it
    title: str | None = Field(None, max_length=200)
    text: str | None = Field(None, max_length=1000)


class ReportedExtras(BaseModel):
    """What a printer's server knows beyond PrusaLink (Prusa Connect does): shown on its page; odometer_e measures the
    filament its prints use. Every field may be left out."""

    material: str | None = Field(None, max_length=40)  # loaded, as the printer names it: PETG, PLA...
    nozzle_diameter: float | None = Field(None, gt=0, le=5)  # mm
    nozzle_hardened: bool | None = None
    nozzle_high_flow: bool | None = None
    temp_chamber: float | None = None
    target_chamber: float | None = None
    print_fan_rpm: float | None = Field(None, ge=0)
    heatbreak_fan_rpm: float | None = Field(None, ge=0)
    speed: float | None = Field(None, ge=0, le=1000)  # %
    flow: float | None = Field(None, ge=0, le=1000)  # %
    odometer_e: float | None = Field(None, ge=0)  # mm of filament the extruder has fed, ever: only ever goes up
    dialog: ReportedDialog | None = None


class PrinterReport(BaseModel):
    """A Prusa printer's status, in PrusaLink's words (docs/plugins.md, "Reporting a printer's status")."""

    reachable: bool = True  # false: the plugin can't hear from the printer now (say why in error)
    error: str | None = Field(None, max_length=300)
    state: str | None = Field(None, max_length=40)  # IDLE, BUSY, PRINTING, PAUSED, FINISHED, STOPPED, ERROR, ATTENTION, READY
    temps: ReportedTemps = ReportedTemps()
    printer_type: str | None = Field(None, max_length=60)  # the model, e.g. COREONE
    firmware: str | None = Field(None, max_length=60)
    job: ReportedJob | None = None  # the print it shows, if any (a finished one too, until it's cleared)
    link: str | None = Field(None, max_length=500)  # where the operator can see it (its page on Prusa Connect, say)
    extras: ReportedExtras | None = None  # beyond PrusaLink: material, nozzle, chamber, fans, a message on its screen


@router.put("/printers/{printer_id}/status")
def report_status(
    printer_id: int, report: PrinterReport, db: Session = Depends(get_db), caller: registry.Caller = Depends(needs("printers:report")),
):
    """
    A Prusa printer's status, from a plugin it's switched to take it from (403 for any other printer: GET /printers
    says which are, in status_from). Farmhand records its prints from these reports as it would from its PrusaLink.
    Send one every few seconds: a printer without one for two minutes shows as unreachable.
    """
    printer = require_printer(db, printer_id)
    try:
        printer_reports.accept(printer, caller.plugin_id, report.model_dump())
    except printer_reports.NotReporter as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
    seen = print_progress.progress(db, printer)  # records its prints, and tells plugins listening for events
    return {"recorded": seen["error"] is None, "error": seen["error"]}


@router.get("/prints/{ticket}/file")
def print_file(ticket: str, caller: registry.Caller = Depends(needs("printers:print", limited=False))):
    """
    The G-code of a print Farmhand is handing the plugin (it POSTed the ticket to the plugin's print path, and waits
    for its answer). Once per ticket, only for the plugin it was given to. X-Farmhand-File is the file's name.
    """
    held = printer_reports.take_ticket(ticket, caller.plugin_id)
    if held is None:
        raise HTTPException(status_code=404, detail="No print is waiting for this plugin under that ticket (it was "
                            "fetched already, or Farmhand stopped waiting).")
    data = held["data"]

    def chunks():
        if isinstance(data, bytes):
            yield data
            return
        data.seek(0)
        while chunk := data.read(1024 * 1024):
            yield chunk

    headers = {"X-Farmhand-File": quote(held["name"])}
    if held["size"] is not None:
        headers["Content-Length"] = str(held["size"])
    return StreamingResponse(chunks(), media_type="application/octet-stream", headers=headers)


@router.get("/farm", dependencies=[Depends(needs("farm:read"))])
def farm(db: Session = Depends(get_db)):
    return answers.farm(db)


# ------------------------------------------------------------------ stream:migrate (a Stream plugin taking over)


@router.get("/stream/migrate")
def stream_migrate_state(db: Session = Depends(get_db), caller: registry.Caller = Depends(needs("stream:migrate"))):
    """Whether the Stream page set-up an older Farmhand saved can still be handed to this plugin: {available, handed_over_at, has_settings}."""
    return handover.stream_state(db, caller.plugin_id)


@router.post("/stream/migrate")
def stream_migrate(db: Session = Depends(get_db), caller: registry.Caller = Depends(needs("stream:migrate"))):
    """The old Stream page's set-up, stream key and YouTube sign-in, handed over once (410 after that). Farmhand keeps its copy."""
    try:
        return handover.stream_handover(db, caller.plugin_id)
    except handover.AlreadyHandedOver as e:
        raise HTTPException(status_code=410, detail=str(e)) from None


# ------------------------------------------------------------------ stream:read (a stream plugin sending Stream control's stream)


@router.get("/stream/design")
def stream_control_design(db: Session = Depends(get_db), caller: registry.Caller = Depends(needs("stream:read"))):
    """
    The stream designed in Stream control: {enabled, design (its grid, words, colours, music...: see docs/plugins.md),
    media: {images, slideshows: [{name, images}], music, error}}. Switched off, or this plugin not brought into it:
    {enabled: false} alone, and the plugin sends its own layout. design.revision goes up by one each time it's saved:
    ask again every few seconds, and change the stream when it has.
    """
    if not stream_control.enabled(db) or not stream_streams.is_chosen(db, caller.plugin_id):
        return {"enabled": False}
    return {"enabled": True, "design": stream_design.settings(db), "media": music_sources.for_stream_plugins(db)}


def _stream_file(db: Session, answer):
    """A file of Stream control's stream: `answer()` (404 while it's switched off, or when the file isn't there)."""
    if not stream_control.enabled(db):
        raise HTTPException(status_code=404, detail="Stream control is switched off.")
    try:
        return answer()
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


@router.get("/stream/pictures/{name}", dependencies=[Depends(needs("stream:read", limited=False))])
def stream_picture(name: str, db: Session = Depends(get_db)):
    return _stream_file(db, lambda: stream_picture_response(stream_media.picture_path(db, None, name)))


@router.get("/stream/slideshows/{show}/pictures/{name}", dependencies=[Depends(needs("stream:read", limited=False))])
def stream_slideshow_picture(show: str, name: str, db: Session = Depends(get_db)):
    return _stream_file(db, lambda: stream_picture_response(stream_media.picture_path(db, show, name)))


@router.get("/stream/music/{name}", dependencies=[Depends(needs("stream:read", limited=False))])
def stream_track(name: str, db: Session = Depends(get_db)):
    """A track of the stream's music, from whichever chosen folder has it (another stream plugin's, passed on)."""
    return _stream_file(db, lambda: stream_track_response(music_sources.find(db, name)))


# ------------------------------------------------------------------ stream:backup (a plugin's own settings, kept with Farmhand's)


@router.put("/backup")
async def put_backup(request: Request, db: Session = Depends(get_db), caller: registry.Caller = Depends(needs("stream:backup"))):
    """Keep this copy of the plugin's own settings ({format: 1, saved_at, settings: {key: text}}, at most 2 MB): kept in
    place of the last, and written to the settings folder (plugin-backups/<id>.json). {saved_at}."""
    raw = await request.body()
    if len(raw) > backups.MOST + 64 * 1024:
        raise HTTPException(status_code=413, detail=f"A plugin's settings copy may be at most {backups.MOST // (1024 * 1024)} MB.")
    try:
        kept = backups.save(db, caller.plugin_id, json.loads(raw or b"null"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    from ..services import config_service  # (not at the top: config_service reads the plugins this module serves)

    config_service.request_mirror(config_service.MirrorScope())
    return kept


@router.get("/backup")
def get_backup(db: Session = Depends(get_db), caller: registry.Caller = Depends(needs("stream:backup"))):
    """The plugin's own copy of its settings, as it sent it ({format, saved_at, settings}): for taking them back when
    the operator restores them. 404 while Farmhand has none."""
    try:
        return backups.get(db, caller.plugin_id)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
