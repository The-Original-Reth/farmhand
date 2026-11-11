from __future__ import annotations

from pydantic import BaseModel, Field


class StreamSettingsIn(BaseModel):
    """What the Stream page saves. Anything left out stays as it was."""

    destination: str | None = None  # "youtube" (the only one for now)
    cameras: list[str] | None = None  # "printer id:camera name": a grid just big enough for these, in this order
    show_status: bool | None = None  # each printer's name and print written under its camera
    layout: str | None = None  # "grid" (all at once) | "cycle" (taking turns)
    seconds_all: int | None = None  # taking turns: how long all the cameras are shown (0: never)
    seconds_each: int | None = None  # taking turns: how long each camera is shown on its own
    resolution: str | None = None  # "720p" | "1080p" | "1440p" (2K)
    border_color: str | None = None  # "#RRGGBB" round each square of the grid
    enabled: bool | None = None  # the Stream page's switch: false stops the stream and keeps it from going live
    font: str | None = None  # the stream's words (a key of live_stream.FONTS), every square's unless it has its own
    color: str | None = None  # "#RRGGBB": the stream's words' colour, likewise
    background: str | None = None  # "#RRGGBB": the stream's own colour, in empty squares and round what doesn't fill its square
    music: bool | None = None  # the stream folder's music played on the stream (false: a silent sound track)
    music_volume: int | None = None  # its loudness, 0 to 100
    music_shuffle: bool | None = None  # in a new order each time the stream starts (false: in name order)
    youtube: dict | None = None  # the video's YouTube settings (privacy, tags, category, made_for_kids, latency, dvr, auto_start, auto_stop)
    delay: int | None = None  # seconds the stream is held before YouTube gets it (0 to 120): stalls shorter than it don't show
    cols: int | None = None  # the grid: 1 to 5 squares across...
    rows: int | None = None  # ...and down
    # each square, row by row: {"camera": "id:name"}, a card {"background", "image", "slideshow", "seconds", "text", "color",
    # "picture_box", "text_box"} (see services/live_stream/squares._cell) or null (empty)
    cells: list[dict | None] | None = None
    title: str | None = Field(None, max_length=1000)  # the YouTube broadcast's title ("" : leave YouTube's as it is)
    description: str | None = Field(None, max_length=20000)  # and its description
    stream_key: str | None = Field(None, max_length=300)  # set it; null or "" leaves the saved one alone
    clear_key: bool = False  # forget the saved key


class YouTubeClientIn(BaseModel):
    """The Google OAuth client ("TVs and Limited Input devices") Farmhand signs in to YouTube with."""

    client_id: str = Field(..., max_length=300)
    client_secret: str | None = Field(None, max_length=300)  # blank keeps the saved one (same client ID)


class YouTubeSignOutIn(BaseModel):
    forget_client: bool = False  # also forget the client ID and secret


class SlideshowOrderIn(BaseModel):
    """A slideshow's pictures in the order chosen (their file names)."""

    order: list[str] = Field(..., max_length=2000)


class SlideshowIn(BaseModel):
    """A new slideshow: a folder of this name in the stream folder's slideshows."""

    name: str = Field(..., max_length=200)
