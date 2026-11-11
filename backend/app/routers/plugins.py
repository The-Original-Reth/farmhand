"""
Plugins, for the operator (the Plugins page): look at the plugin at an address before adding it, add one (its token is
shown once), list them with how each is doing, switch one off or on, give one a new token, remove one. And a
plugin's page shown inside Farmhand: /plugins/<id>/page/... passed on to the plugin wherever it runs (nginx sends the
browser's /plugins/<id>/ here), and /plugins/farmhand-plugin.js for those pages. The rules are in services/plugins/.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFound, answer_errors
from ..services.plugins import answers, pages, registry
from ..services.plugins import manifest as manifests
from .common import require_confirm

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginAddress(BaseModel):
    address: str  # where the plugin runs, like http://192.168.10.215:8080


class PluginInstall(BaseModel):
    permissions: list[str]  # what the operator granted: each one the manifest asks for
    address: str | None = None  # where it runs: its manifest is fetched from <address>/manifest
    only_from_address: bool | None = None  # its token taken only from its address (default: yes, given an address)
    manifest: dict | None = None  # or its farmhand-plugin.json itself, for a container beside Farmhand (no address)
    image: str | None = None  # the Docker image it runs from


class PluginChange(BaseModel):
    enabled: bool | None = None  # off: its token is refused and its page leaves the menu
    only_from_address: bool | None = None
    address: str | None = None  # it moved: the plugin there must be the same one


def _already(e: registry.AlreadyInstalled):
    raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("")
def list_plugins(db: Session = Depends(get_db)):
    return {
        "plugins": [registry.out(p) for p in registry.all_plugins(db)],
        "api_version": manifests.API_VERSION,
        "permissions": manifests.describe(list(manifests.PERMISSIONS)),
    }


@router.post("/preview")
def preview_plugin(body: PluginAddress, db: Session = Depends(get_db)):
    """The plugin at an address, before it's added: its manifest checked and what it asks for, in plain words."""
    with answer_errors():
        return registry.preview(db, body.address)


@router.post("", status_code=201)
def install_plugin(body: PluginInstall, db: Session = Depends(get_db)):
    with answer_errors():
        try:
            if body.address is not None:
                plugin, token = registry.register_by_address(
                    db, body.address, body.permissions, True if body.only_from_address is None else body.only_from_address,
                )
            elif body.manifest is not None:
                plugin, token = registry.register(
                    db, body.manifest, body.permissions, body.image, only_from_address=body.only_from_address,
                )
            else:
                raise ValueError("Give the plugin's address, like http://192.168.10.215:8080.")
        except registry.AlreadyInstalled as e:
            _already(e)
    return {"plugin": registry.out(plugin), "token": token}


# Before /{plugin_id}: a plugin's page loads it as /plugins/farmhand-plugin.js
@router.get("/farmhand-plugin.js", include_in_schema=False)
def plugin_script():
    return pages.script()


@router.get("/{plugin_id}")
def get_plugin(plugin_id: str, db: Session = Depends(get_db)):
    with answer_errors():
        return registry.out(registry.get(db, plugin_id))


@router.patch("/{plugin_id}")
def change_plugin(plugin_id: str, body: PluginChange, db: Session = Depends(get_db)):
    with answer_errors():
        return registry.out(registry.update(db, plugin_id, body.enabled, body.only_from_address, body.address))


@router.post("/{plugin_id}/token")
def new_token(plugin_id: str, db: Session = Depends(get_db)):
    with answer_errors():
        token = registry.new_token(db, plugin_id)
        return {"plugin": registry.out(registry.get(db, plugin_id)), "token": token}


@router.delete("/{plugin_id}", status_code=204)
def remove_plugin(plugin_id: str, confirm: bool = False, db: Session = Depends(get_db)):
    require_confirm(confirm)
    with answer_errors():
        registry.remove(db, plugin_id)
    return Response(status_code=204)


@router.api_route(
    "/{plugin_id}/page/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False,
)
async def plugin_page(plugin_id: str, path: str, request: Request, db: Session = Depends(get_db)):
    """The plugin's own page (and whatever it asks its plugin for), passed on to it at its address."""
    colors = answers.farm(db)["colors"]
    try:
        plugin = registry.get(db, plugin_id)
    except NotFound:
        return pages.message_page(colors, "There's no such plugin", f"No plugin called \"{plugin_id}\" is added to Farmhand.", 404)
    if not plugin.enabled:
        return pages.message_page(
            colors, "This plugin is switched off", f"{plugin.name} is switched off. Switch it on on the Plugins page to use it.", 403,
        )
    address = registry.connection_of(plugin).address
    db.close()  # not held while the plugin answers (an event stream may stay open for hours)
    return await pages.forward(request, plugin_id, address, path, colors)
