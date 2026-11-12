"""
What the stream can be: where it goes, its sizes, its limits and timings, and how its settings are kept.
"""
from __future__ import annotations

import re

SETTINGS_KEY = "live_stream"  # see settings()
STREAM_KEY_KEY = "live_stream_key"  # the stream key itself, on its own

# Where the stream goes: YouTube Live's RTMPS address, the stream key goes on the end. This plugin is for YouTube only
# (Twitch would be a plugin of its own); a setup saved with another destination is read as YouTube.
DESTINATIONS = {
    "youtube": {"label": "YouTube Live", "url": "rtmps://a.rtmps.youtube.com/live2/"},
}
DEFAULT_DESTINATION = "youtube"
KEY_SHAPE = re.compile(r"^[A-Za-z0-9_\-?=&.]{4,200}$")
MAX_SIDE = 5  # the grid is 1x1 to 5x5
MAX_CAMERAS = MAX_SIDE * MAX_SIDE
CAMERA_KEY = re.compile(r"^\d+:.{1,100}$")  # "printer id:camera name", as Monitor names them

FPS = 15
# The sizes the stream can be sent at: (width, height, video bitrate as YouTube suggests for each), and their names
RESOLUTIONS = {
    "720p": (1280, 720, 2500),
    "1080p": (1920, 1080, 2500),  # (YouTube's own advice at 15 frames a second)
    "1440p": (2560, 1440, 4500),
}
RESOLUTION_LABELS = {"720p": "720p (1280×720)", "1080p": "1080p (1920×1080)", "1440p": "2K (2560×1440)"}
DEFAULT_RESOLUTION = "720p"
WIDTH, HEIGHT, _ = RESOLUTIONS[DEFAULT_RESOLUTION]
RETRY_SECONDS = 10  # how long after ffmpeg stops it is started again
STATUS_EVERY = 15  # how often the print progress written on the video is brought up to date
KEPT_LINES = 30  # how much of what ffmpeg said is kept, to say why it stopped

LAYOUTS = ("grid", "cycle")  # the grid all the time, or taking turns
SECONDS = {"seconds_all": (0, 3600, 30), "seconds_each": (3, 3600, 20)}  # (least, most, default); seconds_all 0: never
TITLE_MAX, DESCRIPTION_MAX = 100, 5000  # YouTube's own limits
DEFAULT_BORDER = "#000000"
DEFAULT_BACKGROUND = "#000000"  # the stream's own colour: empty squares, and round anything that doesn't fill its square
BORDER_WIDTH = 3  # px round each square, on the 720-high picture
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
DEFAULT_TEXT_COLOR = "#FFFFFF"  # the stream's words, unless a square has its own
# The video's own YouTube settings (the YouTube settings window), as kept, and what each can be
YOUTUBE_DEFAULTS = {"privacy": "public", "tags": [], "category": "28", "made_for_kids": False, "latency": "normal", "dvr": True,
                    "auto_start": True, "auto_stop": True}
PRIVACIES = ("public", "unlisted", "private")
LATENCIES = ("normal", "low", "ultraLow")
CATEGORIES = ("28", "27", "26", "22", "24", "20")  # Science & Technology, Education, Howto & Style, People & Blogs, Entertainment, Gaming
TAGS_MAX = 500  # YouTube's limit, all the tags together (commas between)
DELAY = (0, 120, 60)  # (least, most, default) seconds the stream is held before YouTube gets it (relay.Buffer)
DEFAULT_MUSIC_VOLUME = 50  # the music's loudness, 0 to 100 (100: as the tracks are)
SAVED = ("destination", "cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "title", "description", "font", "color", "enabled",
         "resolution", "border_color", "background", "music", "music_volume", "music_shuffle", "delay", "youtube")
