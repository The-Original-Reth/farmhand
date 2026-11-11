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
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.plugins import answers, events, limits, registry, remote
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
