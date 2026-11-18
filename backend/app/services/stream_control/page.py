"""What Stream control's page is given in one answer (GET /stream-control), and after each change it makes."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import config_service
from . import design, fonts, layouts, media, schedule, streams


def page(db: Session, with_streams: bool = True) -> dict:
    """
    {design (design.settings), resolutions, fonts, media (media.media: the stream folder's pictures, slideshows and
    music), layouts (the saved ones), schedule ({on, entries}), happened (what the schedule did lately), time_zone (the
    farm's, which the schedule's times are in), streams (each stream plugin and how it's doing; left out when not asked,
    so a change to the stream folder doesn't wait on the plugins)}.
    """
    out = {
        "design": design.settings(db),
        "resolutions": design.resolutions(),
        "fonts": fonts.listed(),
        "media": media.media(db),
        "layouts": layouts.layouts(db),
        "schedule": schedule.schedule(db),
        "happened": schedule.happened(),
        "time_zone": config_service.get_config(db)["preferences"].get("time_zone"),
    }
    if with_streams:
        out["streams"] = streams.listed(db)
    return out
