"""What Stream control's page is given in one answer (GET /stream-control), and after each change it makes."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import farm_settings
from . import design, fonts, layouts, media, music_sources, schedule, streams


def page(db: Session, with_streams: bool = True) -> dict:
    """
    {design (design.settings), resolutions, fonts, media (media.media: the stream folder's pictures, slideshows and
    music), layouts (the saved ones), layouts_revision, schedule ({on, entries}), schedule_revision, happened (what the schedule did lately), time_zone (the
    farm's, which the schedule's times are in), streams (each stream plugin and how it's doing; left out when not asked,
    so a change to the stream folder doesn't wait on the plugins)}.
    """
    found = media.media(db)
    playing = music_sources.tracks(db)
    out = {
        "design": design.settings(db),
        "resolutions": design.resolutions(),
        "fonts": fonts.listed(),
        # the stream folder; music: the stream's tracks from the folders chosen, own_music: those in Stream control's own
        # (only those can be deleted here), music_sources: the folders there are to choose from
        "media": {**found, "music": [t["name"] for t in playing], "own_music": found["music"], "music_tracks": playing,
                  "music_sources": music_sources.sources(db)},
        "layouts": layouts.layouts(db),
        "layouts_revision": layouts.revision(db),  # (sent back with a change, so one saved since isn't overwritten)
        "schedule": schedule.schedule(db),
        "schedule_revision": schedule.revision(db),
        "happened": schedule.happened(),
        "time_zone": farm_settings.get_config(db)["preferences"].get("time_zone"),
    }
    if with_streams:
        out["streams"] = streams.listed(db)
    return out
