from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import storage
from ..database import get_db
from ..mounts import MountError
from ..schemas.network_share import FolderCreate, NetworkShareCreate, NetworkShareOut, NetworkShareUpdate, SharesOut
from ..schemas.storage import BrowseOut, MigrationResult, StorageSettingsOut, StorageSettingsUpdate
from ..services import config_service, network_shares_service, storage_settings_service

router = APIRouter(prefix="/settings/storage", tags=["storage"])


@router.get("", response_model=StorageSettingsOut)
def get_storage_settings(db: Session = Depends(get_db)):
    return storage_settings_service.describe(db)


@router.put("", response_model=StorageSettingsOut)
def update_storage_settings(payload: StorageSettingsUpdate, db: Session = Depends(get_db)):
    """Choose where STL files and/or 3MF files are stored. null resets a location to its default."""
    try:
        out = storage_settings_service.save(db, payload.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    config_service.mirror_quietly(db)  # keep the settings copy current
    return out


@router.get("/browse", response_model=BrowseOut)
def browse_folders(path: str | None = Query(None, description="Folder to list; omit for the top level")):
    """Sub-folders for the folder picker. Only folders under the configured browse root are visible."""
    try:
        return storage.list_subdirs(path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/migrate", response_model=MigrationResult)
def migrate_existing_files(db: Session = Depends(get_db)):
    """Move files stored outside the currently selected locations into them (verified copy, then delete)."""
    return storage_settings_service.migrate(db)


@router.post("/folders", response_model=BrowseOut, status_code=201)
def create_folder(payload: FolderCreate):
    """Make a folder (the picker's "New folder"); returns that new folder's listing so the picker can step into it."""
    try:
        made = storage.create_folder(payload.parent, payload.name)
        return storage.list_subdirs(str(made))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---- network shares: connect a NAS from the web interface ----

def _share_error(e: Exception) -> HTTPException:
    if isinstance(e, network_shares_service.ShareNotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, network_shares_service.ShareInUse) or (isinstance(e, MountError) and e.kind == "busy"):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=422, detail=str(e))


@router.get("/shares", response_model=SharesOut)
def list_shares(db: Session = Depends(get_db)):
    return network_shares_service.list_shares(db)


@router.post("/shares", response_model=NetworkShareOut, status_code=201)
def add_share(payload: NetworkShareCreate, db: Session = Depends(get_db)):
    """Connect a NAS share. It is mounted before it is saved, so only a working connection is kept."""
    try:
        out = network_shares_service.create_share(db, payload.model_dump())
    except ValueError as e:
        raise _share_error(e)
    config_service.mirror_quietly(db)
    return out


@router.patch("/shares/{share_id}", response_model=NetworkShareOut)
def edit_share(share_id: int, payload: NetworkShareUpdate, db: Session = Depends(get_db)):
    try:
        out = network_shares_service.update_share(db, share_id, payload.model_dump(exclude_unset=True))
    except ValueError as e:
        raise _share_error(e)
    config_service.mirror_quietly(db)
    return out


@router.post("/shares/{share_id}/connect", response_model=NetworkShareOut)
def reconnect_share(share_id: int, db: Session = Depends(get_db)):
    try:
        return network_shares_service.reconnect_share(db, share_id)
    except ValueError as e:
        raise _share_error(e)


@router.delete("/shares/{share_id}", status_code=204)
def remove_share(share_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Disconnect and forget a share (files on the NAS are untouched). Refused while it's a chosen storage location."""
    if not confirm:
        raise HTTPException(status_code=409, detail="Pass confirm=true to proceed")
    try:
        network_shares_service.delete_share(db, share_id)
    except ValueError as e:
        raise _share_error(e)
    config_service.mirror_quietly(db)
    return Response(status_code=204)
