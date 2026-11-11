"""
The plugin API, version 1: what a plugin's container may read of Farmhand (docs/plugins.md has every shape). Each call
carries the plugin's token (Authorization: Bearer ...): none or a bad one is 401, and a call outside the permissions
the operator granted it is 403 naming the one it needs. Read-only, and v1 only ever gains fields and endpoints.

Meant to be reached only from inside Docker's network: nginx doesn't pass /plugin-api/ on (see docs/plugins.md for
how that will be enforced on the API's own port).
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.plugins import answers, events, registry
from ..services.plugins.manifest import API_VERSION
from .common import require_printer

router = APIRouter(prefix=f"/plugin-api/v{API_VERSION}", tags=["plugin API"])

NO_TOKEN = "This needs the plugin's token, sent as \"Authorization: Bearer <token>\" (the FARMHAND_TOKEN it was given)."
BAD_TOKEN = (
    "That plugin token isn't valid: it was replaced by a new one, the plugin was removed or turned off, or it was "
    "never made here. The operator can give the plugin a new token on Farmhand's Plugins page."
)


def plugin_caller(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> registry.Caller:
    """The plugin making the call, known by its token; 401 without one Farmhand knows."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail=NO_TOKEN, headers={"WWW-Authenticate": "Bearer"})
    caller = registry.caller(db, token.strip())
    if caller is None:
        raise HTTPException(status_code=401, detail=BAD_TOKEN, headers={"WWW-Authenticate": "Bearer"})
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


@router.get("/events", dependencies=[Depends(needs("prints:read"))])
async def printer_events():
    return StreamingResponse(
        events.stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/farm", dependencies=[Depends(needs("farm:read"))])
def farm(db: Session = Depends(get_db)):
    return answers.farm(db)
