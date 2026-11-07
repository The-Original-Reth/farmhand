from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import answer_errors
from ..services import config_service, farm_cost

# The Farm cost page: the filament every printer used and what it cost, by month. Read only. Its electricity comes
# from each printer's /energy, priced on the page with the Power page's prices.
router = APIRouter(prefix="/farm-cost", tags=["farm cost"])


@router.get("")
def farm_filament(tz: str | None = Query(None, max_length=64), db: Session = Depends(get_db)):
    """
    The filament used by each printer, totalled by month in the viewer's time zone (tz, e.g. "Europe/London"; UTC if
    left out): see services/farm_cost.py. records: where each month's record is saved once it's over, and which are.
    """
    return {**farm_cost.filament_by_month(db, tz), "records": farm_cost.records_status(db)}


class LocationIn(BaseModel):
    path: str | None = None  # null or "" = back to the default


@router.get("/location")
def records_location(db: Session = Depends(get_db)):
    """Where each month's record is saved: {path, is_default, default_path, status} (see services/farm_cost.py)."""
    return farm_cost.location_info(db)


@router.put("/location")
def choose_records_location(payload: LocationIn, db: Session = Depends(get_db)):
    """Choose the folder each month's record is saved in, or go back to the default (path null). 422 says why not."""
    with answer_errors():
        out = farm_cost.set_location(db, payload.path)
    config_service.mirror_quietly(db)  # the settings copy holds which folder it is
    return out
