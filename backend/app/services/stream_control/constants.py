"""
What the stream designed in Stream control can be: its grid's limits, sizes, timings and colours. These are the stream
plugins' own (live_stream/constants.py in the YouTube and Twitch plugins), so a design made here is one they can send.
"""
from __future__ import annotations

import re

MAX_SIDE = 5  # the grid is 1x1 to 5x5
MAX_CAMERAS = MAX_SIDE * MAX_SIDE
CAMERA_KEY = re.compile(r"^\d+:.{1,100}$")  # "printer id:camera name", as Monitor names them

# The sizes the stream can be sent at: (width, height), and their names
RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440)}
RESOLUTION_LABELS = {"720p": "720p (1280×720)", "1080p": "1080p (1920×1080)", "1440p": "2K (2560×1440)"}
DEFAULT_RESOLUTION = "720p"

LAYOUTS = ("grid", "cycle")  # the grid all the time, or taking turns
SECONDS = {"seconds_all": (0, 3600, 30), "seconds_each": (3, 3600, 20)}  # (least, most, default); seconds_all 0: never
TITLE_MAX, DESCRIPTION_MAX = 100, 5000  # YouTube's limits (Twitch's title is shorter: its plugin cuts it)
DEFAULT_BORDER = "#000000"
DEFAULT_BACKGROUND = "#000000"  # the stream's own colour: empty squares, and round anything that doesn't fill its square
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
DEFAULT_TEXT_COLOR = "#FFFFFF"  # the stream's words, unless a square has its own
DELAY = (0, 120, 60)  # (least, most, default) seconds each plugin holds the stream before the site gets it
DEFAULT_MUSIC_VOLUME = 50  # the music's loudness, 0 to 100 (100: as the tracks are)
# The holding screen: what the sites are shown after a stream plugin's own restart, while its delay fills again
HOLDING_DEFAULTS = {"text": "Back in a minute", "image": None, "background": None, "color": None, "font": None}
HOLDING_TEXT_MAX = 300
