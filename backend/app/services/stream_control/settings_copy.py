"""
Stream control in the settings copy (farmhand-config.json's "stream_control"): whether it's on, the design, the saved
layouts and the schedule. Load all settings puts them back only on a Farmhand that has none of its own yet (it only
ever adds). The stream folder's pictures and music are files beside the STL folder already, not copied.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .. import app_settings
from . import ENABLED_KEY, enabled, set_enabled
from . import design, layouts, schedule, streams


def entry(db: Session) -> dict:
    kept = design.settings(db)
    return {
        "enabled": enabled(db),
        "design": {k: kept[k] for k in design.SAVED},
        "layouts": layouts.layouts(db),
        "schedule": schedule.schedule(db),
        "streams": streams.chosen(db),  # the stream plugins brought in (null: all of them)
    }


def restore(db: Session, raw) -> bool:
    """Put back what the copy has, when this Farmhand has no Stream control of its own yet. True when it did."""
    if not isinstance(raw, dict) or not raw:
        return False
    if any(app_settings.get(db, k) is not None
           for k in (ENABLED_KEY, design.DESIGN_KEY, layouts.LAYOUTS_KEY, schedule.SCHEDULE_KEY, streams.CHOSEN_KEY)):
        return False
    if isinstance(raw.get("streams"), list):  # (as ids: a plugin not added here yet is brought in once it is)
        app_settings.put(db, streams.CHOSEN_KEY, json.dumps([x for x in raw["streams"] if isinstance(x, str)]))
        db.commit()
    if isinstance(raw.get("design"), dict):
        design.put_whole(db, raw["design"])
    if isinstance(raw.get("layouts"), list):
        layouts.save(db, raw["layouts"])
    if isinstance(raw.get("schedule"), dict):
        try:
            schedule.save(db, raw["schedule"])
        except ValueError:
            pass
    if raw.get("enabled") is True:
        set_enabled(db, True)
    return True
