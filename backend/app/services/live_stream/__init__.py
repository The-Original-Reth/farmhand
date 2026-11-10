"""
The Stream page: printers' cameras sent live to YouTube (or Twitch) by Farmhand itself, no OBS needed.

The picture is a grid of squares, 1x1 to 5x5, on a background colour, each square holding a camera, a "card" or nothing,
in the order chosen, each with a border round it in the colour chosen. A card is a colour, with a picture or a slideshow
over it if you like, and words over that if you like; its pictures are files in the stream folder (stream_media.py). Taking turns, the picture shows
the whole grid for a while, then each camera on its own, round and round; only the camera on screen is enlarged, the
way Monitor enlarges the one clicked.

What's chosen (where to, the grid and its squares, the words, taking turns, the resolution, the YouTube title and
description) is kept in app_settings; the pictures in the stream folder. The stream key is kept in app_settings
under a key of its own and never leaves Farmhand again: it isn't returned by the API, isn't written to the settings
copy, and is blanked out of anything ffmpeg says.

Going live runs ffmpeg in the API's own container: it reads each camera in the grid (a Mainsail MJPEG stream, go2rtc on
the printer, or a Buddy3D's RTSP), lays the squares out, writes each printer's name and print under its camera, adds the
music (the stream folder's MP3s, round and round) or the silent sound track YouTube insists on, and sends it all to the
destination. If ffmpeg stops (a camera dropped, the
network blinked) it is started again after a short wait, for as long as the stream is meant to be live.

The YouTube broadcast's own title and description are set through YouTube's API (services/youtube_live.py) once the
broadcast has started.
"""
from __future__ import annotations

# What the rest of Farmhand uses. The package, file by file: constants (what the stream can be), fonts, squares (a
# square's choices, checked), choices (the stream's settings, kept and checked), sources (how ffmpeg reads each
# camera), frame (the picture's sizes), cards (a card's square), words (the words on the cameras), picture (the whole
# ffmpeg command), encoders (processor or NVIDIA card), staging (the files going live puts out for ffmpeg), runner (the
# stream itself).
from sqlalchemy.orm import Session

from . import encoders, fonts, runner  # noqa: F401
from .choices import auto_grid, rename_slideshow, save, settings  # noqa: F401
from .constants import DESTINATIONS, RESOLUTION_LABELS, RESOLUTIONS, SETTINGS_KEY  # noqa: F401
from .fonts import DEFAULT_FONT, FONT, FONTS, font_file  # noqa: F401
from .picture import TURNS_FOR, Look, command, grid, timetable, windows  # noqa: F401
from .runner import stream  # noqa: F401
from .sources import Source, input_args  # noqa: F401
from .squares import _camera_cell, _cell  # noqa: F401 (the settings copy uses the same rules)
from .words import status_line  # noqa: F401

from .. import stream_media, youtube_live


def page(db: Session) -> dict:
    """Everything the Stream page shows: {settings, media (the stream folder's pictures, slideshows and music, stream_media.media),
    status, destinations, resolutions, fonts (what a square's words can be written in), youtube}."""
    return {
        "settings": settings(db),
        "media": stream_media.media(db),
        "status": stream.status(),
        "destinations": [{"key": k, "label": v["label"]} for k, v in DESTINATIONS.items()],
        "resolutions": [{"key": k, "label": RESOLUTION_LABELS[k]} for k in RESOLUTIONS],
        "fonts": [{"key": k, "label": v[0], "generic": v[2]} for k, v in FONTS.items()],
        "youtube": youtube_live.account(db),
    }
