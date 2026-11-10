"""
The ffmpeg command that makes the picture: the squares laid out (a card's square is cards.py's, the words on the
cameras words.py's), taking turns, the sound (the music, or silence), and how it's compressed (encoders.py) and where
it's sent.
"""
from __future__ import annotations

import math

from dataclasses import dataclass

from .constants import DEFAULT_BACKGROUND, DEFAULT_BORDER, DEFAULT_RESOLUTION, FPS, HEIGHT, WIDTH
from .cards import card_square
from .choices import auto_grid
from .encoders import encoder_args
from .frame import Frame
from .sources import Source
from .words import camera_words, filter_path, full_words

TURNS_FOR = 24 * 3600  # the timetable of turns covers a day; ffmpeg then ends and is started again at once


def grid(n: int, width: int = WIDTH, height: int = HEIGHT) -> tuple[int, int, int, int]:
    """(columns, rows, square width, square height) of the near-square grid for n squares, sizes even."""
    cols, rows = auto_grid(n)
    return cols, rows, (width // cols) // 2 * 2, (height // rows) // 2 * 2


def windows(n: int, seconds_all: int, seconds_each: int) -> tuple[int, list[tuple[int, int]]]:
    """
    Taking turns: (the whole round in seconds, each camera's [from, to) within it). All the cameras come first, for
    seconds_all, then each camera on its own for seconds_each. With seconds_all 0 the first camera's turn starts it.
    """
    period = seconds_all + n * seconds_each
    return period, [(seconds_all + i * seconds_each, seconds_all + (i + 1) * seconds_each) for i in range(n)]


def timetable(n: int, seconds_all: int, seconds_each: int, horizon: int = TURNS_FOR, clock: float = 0) -> str:
    """
    Taking turns, as ffmpeg's sendcmd reads it: at each turn, which view (0: all the cameras, 1: one on its own) and
    which camera. Covers `horizon` seconds of stream. `clock`: the time of day (seconds) the stream starts at: the
    rounds are counted from midnight 1970, as the page counts them, so the stream starts on the turn the page shows.
    """
    period, turns = windows(n, seconds_all, seconds_each)
    phase = round(clock % period, 3)
    events = ([(0, "streamselect@view map 0;")] if seconds_all else []) + [
        (start, f"{'streamselect@view map 1, ' if seconds_all else ''}streamselect@pick map {i};") for i, (start, _) in enumerate(turns)]
    lines = []
    if phase:  # partway through a round: the turn already under way, at once
        lines.append(f"0 {max((e for e in events if e[0] <= phase), key=lambda e: e[0])[1]}")
    for r in range(math.ceil((horizon + phase) / period) + 1):
        for start, cmd in events:
            at = round(r * period + start - phase, 3)
            if (0 < at or (at == 0 and not phase)) and at < horizon:
                lines.append(f"{at:g} {cmd}")
    return "\n".join(lines) + "\n"


@dataclass
class Look:
    """
    How the picture is put together.

    cells: the grid's squares row by row, cols x rows of them (None: the cameras, in a grid just big enough), each one of
      ("camera", its place in srcs[, its square's own choices (_camera_cell), or just its background colour]),
      ("card", {background, pictures: [files] (none, one picture, or a slideshow's), seconds, words: its words' file
      | None, picture_words: {place in the slideshow: {words, text_box}}, color, font, band, picture_box,
      picture_boxes, text_box}), or None (empty).
    status_files: the words under each camera, a file per camera (None: no words).
    cycle: taking turns, (seconds on the whole grid, on each camera) (None: the grid all the time); turns_file: its
      timetable (timetable()).
    music: the music's playlist, as ffmpeg's concat reads it (staging.playlist: round after round of the tracks, for a
      day), played at music_volume (0 to 100) (None: a silent sound track).
    """

    status_files: list[str] | None = None
    cycle: tuple[int, int] | None = None
    turns_file: str | None = None
    resolution: str = DEFAULT_RESOLUTION  # one of RESOLUTIONS
    border_color: str = DEFAULT_BORDER  # round each square
    background: str = DEFAULT_BACKGROUND  # the stream's colour, behind everything
    clock: float = 0  # the time of day (seconds since 1970) at the stream's start: slideshows and turns count from it
    encoder: str = "cpu"  # "cpu" (libx264) or "nvenc" (an NVIDIA card's own encoder; see encoders.encoder)
    font: str | None = None  # the stream's words, unless a square has its own (None: DEFAULT_FONT)
    color: str | None = None  # (None: DEFAULT_TEXT_COLOR)
    cols: int | None = None
    rows: int | None = None
    cells: list | None = None
    music: str | None = None
    music_volume: int = 50


def command(ffmpeg: str, srcs: list[Source], url: str, look: Look | None = None) -> list[str]:
    """
    The whole ffmpeg command: the grid's squares laid out, each camera turned as Mainsail shows it and fitted into its
    square with the printer and its print written along its foot; each card its colour, its picture (or slideshow,
    each picture over the first in its own seconds) fitted over it and its words over that; an empty square the stream's
    background colour; every square with a border round it; the music (or a silent sound track: YouTube wants sound);
    sent as FLV to `url`.

    Taking turns works the way Monitor's enlarging does: only the camera on screen is made full size. Every camera's
    picture goes to a switch (streamselect "pick") that lets through only the one whose turn it is, and only that one
    is enlarged; a second switch ("view") chooses between it and the grid. The timetable (look.turns_file, see
    timetable()) moves both switches. It covers a day, so the command then ends (-t) and the stream starts it again.
    """
    look = look or Look()
    n = len(srcs)
    if look.cells is None:
        cols, rows = auto_grid(n)
        cells = [("camera", i) for i in range(n)] + [None] * (cols * rows - n)
    else:
        cols, rows, cells = look.cols, look.rows, list(look.cells)
    cycle = look.cycle if n > 1 else None
    need_grid = cycle is None or cycle[0] > 0
    frame = Frame.of(look.resolution, cols, rows, look.background, look.border_color)

    args = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin"]
    for s in srcs:
        args += ["-thread_queue_size", "64", *s.input_args]
    if look.music:  # read as it plays (-re)
        args += ["-re", "-f", "concat", "-safe", "0", "-i", look.music]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    inputs = [n + 1]  # the next input's number: each picture shown is an input of its own, read once a second

    def picture(path: str) -> int:
        args.extend(["-loop", "1", "-framerate", "1", "-i", path])
        inputs[0] += 1
        return inputs[0] - 1

    own = _cameras_own(cells, look)
    stream_words = _stream_words(look)
    parts = []
    for i, s in enumerate(srcs):  # each camera turned, then to the grid, to taking turns, or both
        base = ",".join([*s.turn, "setpts=PTS-STARTPTS", f"fps={FPS}", "setsar=1"])
        outs = ([f"[g{i}]"] if need_grid else []) + ([f"[s{i}]"] if cycle else [])
        parts.append(f"[{i}:v]{base}" + (f",split=2{''.join(outs)}" if len(outs) == 2 else outs[0]))
    if need_grid:
        for c, cell in enumerate(cells):
            if cell and cell[0] == "camera":
                parts.append(_camera_square(c, cell[1], own.get(cell[1], stream_words), frame, look.status_files))
            elif cell and cell[0] == "card":
                parts.append(card_square(c, cell[1], frame, picture, clock=look.clock, font=look.font, color=look.color))
            else:
                parts.append(f"{frame.plain()},{frame.border}[c{c}]")
        parts.append(_laid_out(len(cells), cols, frame))
    video = "[grid]"
    if cycle is not None:
        parts += _turns(n, need_grid, frame, look.status_files, lambda i: own.get(i, stream_words))
        video = "[turns]"
    if look.turns_file:  # the timetable moves the switches of taking turns
        parts.append(f"{video}sendcmd=f={filter_path(look.turns_file)}[timed]")
        video = "[timed]"
    kbps = frame.kbps
    args += ["-filter_complex", ";".join(parts), "-map", video, "-map", f"{n}:a"]
    if look.music:
        args += ["-af", music_filter(look.music_volume)]
    args += [*encoder_args(look.encoder), "-pix_fmt", "yuv420p", "-r", str(FPS),
             "-g", str(FPS * 2), "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
    if look.turns_file or look.music:  # the timetable and the playlist cover a day: then ffmpeg is started again
        args += ["-t", str(TURNS_FOR)]
    args += ["-f", "flv", url]
    return args


def music_filter(volume: int) -> str:
    """The music as it goes out: one steady sound track (tracks of different sample rates or mono ones made alike, gaps
    filled, silence once the playlist is done), at `volume` (0 to 100, squared, so the slider's middle sounds about
    half as loud: -12 dB)."""
    return f"aresample=async=1,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={(volume / 100) ** 2:.4g},apad"


def _stream_words(look: Look) -> dict:
    """The stream's own font and colour for the cameras' words, as a camera square's choices name them."""
    return {k: v for k, v in (("words_font", look.font), ("words_color", look.color)) if v}


def _cameras_own(cells: list, look: Look) -> dict[int, dict]:
    """Each camera's own square choices, by its place in srcs ("camera", place, its cell or just its colour (tests)),
    over the stream's words' font and colour."""
    own = {}
    for cell in cells or []:
        if cell and cell[0] == "camera" and len(cell) > 2 and cell[2]:
            own[cell[1]] = cell[2] if isinstance(cell[2], dict) else {"background": cell[2]}
    stream_words = _stream_words(look)
    return {i: {**stream_words, **{k: v for k, v in mine.items() if v is not None}} for i, mine in own.items()}


def _camera_square(c: int, i: int, mine: dict, frame: Frame, status_files: list[str] | None) -> str:
    """Square c, camera i (from [g{i}]): fitted in, its own colour round it, its words along its foot (sized to its
    square, 20 px in a quarter of a 720p picture, unless it has its own size), its border."""
    tw, th, edge = frame.tw, frame.th, frame.edge
    colour = (mine.get("background") or "#" + frame.back).lstrip("#")
    chain = [f"scale={tw}:{th}:force_original_aspect_ratio=decrease", f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=0x{colour}"]
    if status_files and mine.get("show_words", True):
        if mine.get("words_size"):
            size = max(frame.px(8), round(mine["words_size"] * th))
            chain.append(camera_words(status_files[i], size, size * 2 // 3 + edge, max(2, size // 3), size // 2 + edge, mine))
        else:
            small = max(frame.px(11), min(th // 18, tw // 32))
            chain.append(camera_words(status_files[i], small, small * 2 // 3 + edge, frame.px(6), small // 2 + edge, mine))
    return f"[g{i}]{','.join(chain)},{frame.border}[c{c}]"


def _laid_out(count: int, cols: int, frame: Frame) -> str:
    """The squares [c0]... laid out in their grid and fitted to the stream: [grid]."""
    tiles = "".join(f"[c{c}]" for c in range(count))
    if count == 1:
        return f"{tiles}{frame.full_size}[grid]"
    layout = "|".join(f"{(c % cols) * frame.tw}_{(c // cols) * frame.th}" for c in range(count))
    return f"{tiles}xstack=inputs={count}:layout={layout}:fill=0x{frame.back},{frame.full_size}[grid]"


def _turns(n: int, need_grid: bool, frame: Frame, status_files: list[str] | None, own_of) -> list[str]:
    """Taking turns: each camera (from [s{i}]) with its words written on its own picture, the switch that lets the one
    whose turn it is through, enlarged ([full]), and the switch between it and the grid: [turns]."""
    parts, picked = [], ""
    for i in range(n):
        mine = own_of(i)
        if not status_files or not mine.get("show_words", True):
            picked += f"[s{i}]"
            continue
        parts.append(f"[s{i}]{camera_words(status_files[i], **full_words(mine), own=mine)}[w{i}]")
        picked += f"[w{i}]"
    parts.append(f"{picked}streamselect@pick=inputs={n}:map=0,{frame.full_size}[full]")
    parts.append("[grid][full]streamselect@view=inputs=2:map=0[turns]" if need_grid else "[full]null[turns]")
    return parts
