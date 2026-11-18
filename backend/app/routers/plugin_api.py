"""
The plugin API, version 1: what a plugin's container may read of Farmhand (docs/plugins.md has every shape). Each call
carries the plugin's token (Authorization: Bearer ...): none or a bad one is 401, and a call outside the permissions
the operator granted it is 403 naming the one it needs. Read-only, and v1 only ever gains fields and endpoints.

Reached over the farm's network on the API's port (a plugin may run on another machine), never through the web
page's server (nginx doesn't pass /plugin-api/ on). Besides the token: a plugin set to "only accept calls from its
address" has its token refused from anywhere else (403), and each token may make RATE calls a second (429 beyond).
"""
from __future__ import annotations

import math
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFound
from ..services import stream_control
from ..services.plugins import answers, events, handover, limits, registry, remote
from ..services.plugins.manifest import API_VERSION
from ..services.stream_control import design as stream_design
from ..services.stream_control import media as stream_media
from ..services.stream_control import streams as stream_streams
from .common import require_printer

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
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail=NO_TOKEN, headers={"WWW-Authenticate": "Bearer"})
    token = token.strip()
    wait = limits.allow(registry.hash_token(token))
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


def needs(permission: str) -> Callable[..., registry.Caller]:
    """A dependency: the calling plugin, which must have been granted this permission (403 naming it otherwise)."""

    def check(caller: registry.Caller = Depends(plugin_caller)) -> registry.Caller:
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
    found = stream_media.media(db)
    return {"enabled": True, "design": stream_design.settings(db),
            "media": {k: found[k] for k in ("images", "slideshows", "music", "error")}}


def _stream_file(db: Session, find):
    """A file of Stream control's stream folder (404 while it's switched off, or when the file isn't there)."""
    if not stream_control.enabled(db):
        raise HTTPException(status_code=404, detail="Stream control is switched off.")
    try:
        path = find()
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    kind = stream_media.PICTURE_TYPES.get(path.suffix.lower()) or stream_media.TRACK_TYPES.get(path.suffix.lower())
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "no-cache"})


@router.get("/stream/pictures/{name}", dependencies=[Depends(needs("stream:read"))])
def stream_picture(name: str, db: Session = Depends(get_db)):
    return _stream_file(db, lambda: stream_media.picture_path(db, None, name))


@router.get("/stream/slideshows/{show}/pictures/{name}", dependencies=[Depends(needs("stream:read"))])
def stream_slideshow_picture(show: str, name: str, db: Session = Depends(get_db)):
    return _stream_file(db, lambda: stream_media.picture_path(db, show, name))


@router.get("/stream/music/{name}", dependencies=[Depends(needs("stream:read"))])
def stream_track(name: str, db: Session = Depends(get_db)):
    return _stream_file(db, lambda: stream_media.track_path(db, name))
