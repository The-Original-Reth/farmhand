"""
The plugin API, version 1: what a plugin's container may read of Farmhand (docs/plugins.md has every shape). Each call
carries the plugin's token (Authorization: Bearer ...): none or a bad one is 401, and a call outside the permissions
the operator granted it is 403 naming the one it needs. It only reads, except what a write permission allows
(library:write, prints:send), and v1 only ever gains fields and endpoints.

Reached over the farm's network on the API's port (a plugin may run on another machine), never through the web
page's server (nginx doesn't pass /plugin-api/ on). Besides the token: a plugin set to "only accept calls from its
address" has its token refused from anywhere else (403), and each token may make RATE calls a second (429 beyond).
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..services import library_records, project_records
from ..services.plugins import answers, events, handover, library, limits, registry, remote
from ..services.plugins.manifest import API_VERSION
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
    return {
        "plugin_id": caller.plugin_id, "permissions": sorted(caller.permissions), "api_version": API_VERSION,
        # where Farmhand reaches it (http://<id>:<port> for one added from its manifest alone, beside Farmhand)
        "address": caller.address,
    }


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


# ------------------------------------------------------------------ a slicer plugin: library:read, library:write, prints:send


@router.get("/library/files", dependencies=[Depends(needs("library:read"))])
def library_files(ref: list[str] = Query(default=[]), db: Session = Depends(get_db)):
    """What each file the refs name is: {files: [{ref, kind, name, version, available, sliceable, printer_id, ...}]}"""
    with answer_errors():
        return library.describe(db, ref)


@router.get("/library/file", dependencies=[Depends(needs("library:read"))])
def library_file(ref: str, db: Session = Depends(get_db)):
    """The file itself"""
    with answer_errors():
        path, name = library.file_of(db, ref)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


def _refs(raw: str) -> list[str]:
    try:
        refs = json.loads(raw)
    except ValueError:
        refs = None
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        raise HTTPException(status_code=422, detail="refs must be a JSON list of the files it was sliced from, like [\"model:12\"].")
    return refs


@router.get("/library/sliced/plan", dependencies=[Depends(needs("library:write"))])
def sliced_plan(
    printer_id: int, ref: list[str] = Query(default=[]), name: str | None = None, project_name: str | None = None,
    db: Session = Depends(get_db),
):
    """Where a 3MF sliced from these files for this printer would go, and its name, before it's saved"""
    with answer_errors():
        return library.plan(db, ref, printer_id, name, project_name).out()


@router.post("/library/sliced", status_code=201, dependencies=[Depends(needs("library:write"))])
def sliced_save(
    printer_id: int = Form(...), refs: str = Form(...), threemf: UploadFile = File(...),
    gcode: UploadFile | None = File(default=None), name: str | None = Form(default=None),
    project_name: str | None = Form(default=None), db: Session = Depends(get_db),
):
    """File a sliced 3MF (and its G-code) where the files it was sliced from are, as /library/sliced/plan says"""
    with answer_errors():
        out = library.save(
            db, _refs(refs), printer_id, threemf.file, gcode.file if gcode else None, gcode.filename if gcode else None,
            name, project_name,
        )
    # what the API's own pages would have written after the same change (change_hooks.py can't tell from the path)
    if out.get("bundle_id"):
        library_records.request_write("bundle", out["bundle_id"])
    if out.get("project_id"):
        project_records.request_write(out["project_id"])
    return out


@router.post("/printers/{printer_id}/print", dependencies=[Depends(needs("prints:send"))])
def send_print(printer_id: int, gcode: UploadFile = File(...), db: Session = Depends(get_db)):
    """Send a G-code to the printer and start it: {sent, printer}. 409 while it's busy, 502 when it can't be reached."""
    with answer_errors():
        return library.send(db, printer_id, gcode.filename, gcode.file)
