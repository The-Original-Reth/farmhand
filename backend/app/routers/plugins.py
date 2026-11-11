"""
Installing plugins, for the operator: register one from its manifest with the permissions granted (its token is
shown once), list them, give one a new token, remove one. The Plugins page (a later step) uses these; the rules are
in services/plugins/registry.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..services.plugins import manifest as manifests
from ..services.plugins import registry
from .common import require_confirm

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginInstall(BaseModel):
    manifest: dict  # the plugin's farmhand-plugin.json
    permissions: list[str]  # what the operator granted: each one the manifest asks for
    image: str | None = None  # the Docker image it runs from


@router.get("")
def list_plugins(db: Session = Depends(get_db)):
    return {
        "plugins": [registry.out(p) for p in registry.all_plugins(db)],
        "api_version": manifests.API_VERSION,
        "permissions": manifests.describe(list(manifests.PERMISSIONS)),
    }


@router.post("", status_code=201)
def install_plugin(body: PluginInstall, db: Session = Depends(get_db)):
    with answer_errors():
        try:
            plugin, token = registry.register(db, body.manifest, body.permissions, body.image)
        except registry.AlreadyInstalled as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
    return {"plugin": registry.out(plugin), "token": token}


@router.get("/{plugin_id}")
def get_plugin(plugin_id: str, db: Session = Depends(get_db)):
    with answer_errors():
        return registry.out(registry.get(db, plugin_id))


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
