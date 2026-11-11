"""
The Stream plugin's engine: printers' cameras sent live to YouTube, no OBS needed. Copied from Farmhand's own Stream
page (backend/app/services/live_stream/), and changed only where a plugin must differ: settings in the plugin's own
store, cameras and prints from the plugin API, and each camera read by its own feeder (feeders.py).

The picture is a grid of squares, 1x1 to 5x5, on a background colour, each square holding a camera, a "card" or nothing,
in the order chosen, each with a border round it in the colour chosen. A card is a colour, with a picture or a slideshow
over it if you like, and words over that if you like; its pictures are files in the stream folder (stream_media.py).
Taking turns, the picture shows the whole grid for a while, then each camera on its own, round and round.

What's chosen is kept in the plugin's store (store.py); the pictures in the stream folder. The stream key is kept there
under a key of its own and never leaves the plugin again: it isn't returned by its API and is blanked out of anything
ffmpeg says.

Going live starts a feeder per camera (Farmhand gives each one's address), then the picture ffmpeg, which reads the
feeders' steady pipes (a camera that stops is a "Camera down" square), lays the squares out, writes each printer's
name and print under its camera, adds the music (the stream folder's MP3s, fed to ffmpeg as they play, music.py) or
the silent sound track YouTube insists on, and sends it all to the destination. If ffmpeg stops it is started again
after a short wait, for as long as the stream is meant to be live, and after the plugin's own restart too.

Signed in to YouTube, the plugin makes, changes, watches and ends the broadcast itself through YouTube's API
(broadcast.py, over youtube_live.py); with a pasted key, YouTube makes it.
"""
from __future__ import annotations

# What the rest of the plugin uses. The package, file by file: constants (what the stream can be), fonts, squares (a
# square's choices, checked), choices (the stream's settings, kept and checked), sources (how ffmpeg reads each
# camera), frame (the picture's sizes), cards (a card's square), words (the words on the cameras), picture (the whole
# ffmpeg command), music (the music, fed to ffmpeg as it plays), encoders (processor or NVIDIA card), staging (the files going live puts out for ffmpeg), feeders (each
# camera's reader, and the "Camera down" square), runner (the stream itself).
from ..store import Session

from . import broadcast, encoders, fonts, music, runner  # noqa: F401
from .choices import auto_grid, rename_slideshow, save, settings  # noqa: F401
from .constants import DESTINATIONS, RESOLUTION_LABELS, RESOLUTIONS, SETTINGS_KEY  # noqa: F401
from .fonts import DEFAULT_FONT, FONT, FONTS, font_file  # noqa: F401
from .picture import TURNS_FOR, Look, command, grid, timetable, windows  # noqa: F401
from .runner import stream  # noqa: F401
from .sources import Source, sources  # noqa: F401
from .squares import _camera_cell, _cell  # noqa: F401 (saved layouts use the same rules)
from .words import status_line  # noqa: F401

from .. import stream_media, youtube_live


def page(db: Session) -> dict:
    """Everything the Stream page shows: {settings, media (the stream folder's pictures, slideshows and music, stream_media.media),
    status, destinations, resolutions, fonts (what a square's words can be written in), youtube, test_destination (where
    the stream goes instead of YouTube while the plugin is being tried out, or None)}."""
    from .. import config

    return {
        "test_destination": config.settings.test_destination,
        "settings": settings(db),
        "media": stream_media.media(db),
        "status": stream.status(),
        "destinations": [{"key": k, "label": v["label"]} for k, v in DESTINATIONS.items()],
        "resolutions": [{"key": k, "label": RESOLUTION_LABELS[k]} for k in RESOLUTIONS],
        "fonts": [{"key": k, "label": v[0], "generic": v[2]} for k, v in FONTS.items()],
        "youtube": youtube_live.account(db),
    }
