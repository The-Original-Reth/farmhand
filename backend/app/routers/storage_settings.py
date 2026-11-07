from __future__ import annotations

from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import storage
from ..database import get_db
from ..errors import answer_errors
from ..mounts import MountError
from ..schemas.network_share import FolderCreate, NetworkShareCreate, NetworkShareOut, NetworkShareUpdate, SharesOut
from ..schemas.storage import BrowseOut, MigrationResult, SaveLocationIn, StorageSettingsOut, StorageSettingsUpdate
from ..services import config_service, network_shares_service, save_location_service, storage_settings_service
from .common import require_confirm

router = APIRouter(prefix="/settings/storage", tags=["storage"])


@router.get("", response_model=StorageSettingsOut)
def get_storage_settings(db: Session = Depends(get_db)):
    return storage_settings_service.describe(db)


@router.put("", response_model=StorageSettingsOut)
def update_storage_settings(payload: StorageSettingsUpdate, db: Session = Depends(get_db)):
    """Choose where STL files and/or 3MF files are stored. null resets a location to its default."""
    with answer_errors():
        out = storage_settings_service.save(db, payload.model_dump(exclude_unset=True))
    config_service.mirror_quietly(db)  # keep the settings copy current
    return out


@router.get("/save-location")
def get_save_location(db: Session = Depends(get_db)):
    """The save location as typed (null until set) and the folder each kind of file goes to: {address, folders: {stl,
    threemf, project, farm_cost, config}}."""
    return save_location_service.describe(db)


@router.put("/save-location")
def set_save_location(payload: SaveLocationIn, db: Session = Depends(get_db)):
    """
    One place on the NAS for everything: connects to the address (reusing the share already there), and uses or makes
    STL, 3MF, Projects, Farm cost and Farmhand Configs inside it. 422 with the reason when it can't (the NAS refusing
    the login, say). config_choice is set when Farmhand Configs already holds saved settings: load or replace them.
    """
    with _share_errors():
        return save_location_service.set_save_location(db, payload.model_dump(exclude_unset=True))


@router.get("/browse", response_model=BrowseOut)
def browse_folders(path: str | None = Query(None, description="Folder to list; omit for the top level")):
    """Sub-folders for the folder picker. Only folders under the configured browse root are visible."""
    with answer_errors():
        return storage.list_subdirs(path)


@router.post("/migrate", response_model=MigrationResult)
def migrate_existing_files(db: Session = Depends(get_db)):
    """Move files stored outside the currently selected locations into them (verified copy, then delete)."""
    return storage_settings_service.migrate(db)


@router.post("/folders", response_model=BrowseOut, status_code=201)
def create_folder(payload: FolderCreate):
    """Make a folder (the picker's "New folder"); returns that new folder's listing so the picker can step into it."""
    with answer_errors():
        made = storage.create_folder(payload.parent, payload.name)
        return storage.list_subdirs(str(made))


# ---- network shares: connect a NAS from the web interface ----

@contextmanager
def _share_errors():
    """What the share services raise, as answers: no such share 404; still in use, or busy, 409; anything else 422."""
    try:
        yield
    except ValueError as e:
        if isinstance(e, network_shares_service.ShareNotFound):
            status = 404
        elif isinstance(e, network_shares_service.ShareInUse) or (isinstance(e, MountError) and e.kind == "busy"):
            status = 409
        else:
            status = 422
        raise HTTPException(status_code=status, detail=str(e)) from None


@router.get("/shares", response_model=SharesOut)
def list_shares(db: Session = Depends(get_db)):
    return network_shares_service.list_shares(db)


@router.post("/shares", response_model=NetworkShareOut, status_code=201)
def add_share(payload: NetworkShareCreate, db: Session = Depends(get_db)):
    """Connect a NAS share. It is mounted before it is saved, so only a working connection is kept."""
    with _share_errors():
        out = network_shares_service.create_share(db, payload.model_dump())
    config_service.mirror_quietly(db)
    return out


@router.patch("/shares/{share_id}", response_model=NetworkShareOut)
def edit_share(share_id: int, payload: NetworkShareUpdate, db: Session = Depends(get_db)):
    with _share_errors():
        out = network_shares_service.update_share(db, share_id, payload.model_dump(exclude_unset=True))
    config_service.mirror_quietly(db)
    return out


@router.post("/shares/{share_id}/connect", response_model=NetworkShareOut)
def reconnect_share(share_id: int, db: Session = Depends(get_db)):
    with _share_errors():
        return network_shares_service.reconnect_share(db, share_id)


@router.delete("/shares/{share_id}", status_code=204)
def remove_share(share_id: int, confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Disconnect and forget a share (files on the NAS are untouched). Refused while it's a chosen storage location."""
    require_confirm(confirm, "Pass confirm=true to proceed")
    with _share_errors():
        network_shares_service.delete_share(db, share_id)
    config_service.mirror_quietly(db)
    return Response(status_code=204)
