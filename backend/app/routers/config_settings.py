from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..schemas.config import (
    ConfigOut, ConfigSaveOut, ConfigUpdate, InspectOut, LocationResult, LocationUpdate, MirrorOut, RestoreOut, SaveAllIn,
    SaveAllOut,
)
from ..services import config_service

router = APIRouter(prefix="/settings/config", tags=["settings"])


@router.get("", response_model=ConfigOut)
def get_settings(db: Session = Depends(get_db)):
    """The settings the server holds (appearance, display preferences) and where their copy is kept."""
    return {"config": config_service.get_config(db), "location": config_service.describe(db)}


@router.put("", response_model=ConfigSaveOut)
def save_settings(payload: ConfigUpdate, db: Session = Depends(get_db)):
    """Save settings on the server, and refresh the copy in the chosen network folder (if there is one)."""
    config = config_service.save_config(db, payload.model_dump(exclude_unset=True))
    return {"config": config, "mirror": config_service.mirror(db)}


@router.get("/location/inspect", response_model=InspectOut)
def inspect_folder(path: str = Query(...), db: Session = Depends(get_db)):
    """Look at a folder before choosing it: is it usable, and does it already hold a settings file?"""
    with answer_errors():
        return config_service.inspect_location(path)


@router.put("/location", response_model=LocationResult)
def choose_location(payload: LocationUpdate, db: Session = Depends(get_db)):
    """
    Choose the network folder the settings copy is written to (null = none). A folder that already holds a
    settings file is never overwritten without being asked: if_exists is "ask", "restore" or "overwrite".
    """
    with answer_errors():
        return config_service.set_location(db, payload.path, payload.if_exists)


@router.post("/save-now", response_model=MirrorOut)
def save_now(db: Session = Depends(get_db)):
    """Write the copy again right now (for after a share has come back)."""
    if not config_service.location_path(db):
        raise HTTPException(status_code=422, detail="Choose a settings folder first.")
    return config_service.mirror(db)


@router.post("/save-all", response_model=SaveAllOut)
def save_all(payload: SaveAllIn, db: Session = Depends(get_db)):
    """
    Save all: every setting, printer and model file written to the settings folder now. With no folder chosen,
    "farmhand-configs" beside the STL folder is used; one already holding settings is never overwritten unless
    if_exists says so (needs_choice comes back instead, with what's there). 503 while the STL share is away.
    """
    with answer_errors():
        return config_service.save_all(db, payload.if_exists)


@router.post("/restore", response_model=RestoreOut)
def restore_settings(db: Session = Depends(get_db)):
    """Load the settings file in the chosen folder. Passwords are never in it: shares come back needing theirs."""
    with answer_errors():
        result = config_service.restore(db)
    config_service.mirror_quietly(db)
    return result
