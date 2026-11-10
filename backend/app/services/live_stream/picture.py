"""
The ffmpeg command that makes the picture: the squares laid out, the words written, taking turns, and where it's sent.
"""
from __future__ import annotations

import math
import os

from dataclasses import dataclass

from .. import stream_media
from .constants import DEFAULT_TEXT_COLOR, BORDER_WIDTH, DEFAULT_BACKGROUND, DEFAULT_BORDER, DEFAULT_RESOLUTION, FPS, HEIGHT, RESOLUTIONS, WIDTH
from .fonts import font_file
from .squares import SLIDE_SECONDS, _picture_box, _text_box
from .choices import auto_grid
from .sources import Source

# ------------------------------------------------------------------ the ffmpeg command


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


def _filter_path(path: str) -> str:
    """A file's path as an ffmpeg filter option: forward slashes, and its : and ' escaped."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _words(path: str, size: int | str, foot: int | str, border: int | str = 6, left: int | str = 10, own: dict | None = None) -> str:
    """The words under a camera; `own`: its square's choices (_camera_cell: words_color, words_font)."""
    own = own or {}
    color = (own.get("words_color") or DEFAULT_TEXT_COLOR).lstrip("#")
    return (f"drawtext=fontfile={_filter_path(font_file(own.get('words_font')))}:textfile={_filter_path(path)}:reload=1:expansion=none"
            f":fontsize={size}:fontcolor=0x{color}:box=1:boxcolor=black@0.6:boxborderw={border}:x={left}:y=h-th-{foot}")


# The words on a camera shown on its own, taking turns: written on the camera's own picture before it's enlarged, so
# sized to it (28 px on the 720-high stream, whatever the camera's size)
FULL_WORDS = {"size": "h/26", "foot": "h/30", "border": "h/120", "left": "w/128"}
TURNS_FOR = 24 * 3600  # the timetable of turns covers a day; ffmpeg then ends and is started again at once


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
    How the picture is put together. cells: the grid's squares row by row, each ("camera", its place in srcs[, its square's own
    choices (_camera_cell) | just its background colour]), ("card",
    {background, pictures: [files] (none, one picture, or a slideshow's), seconds, words: its words' file | None, color,
    picture_box, text_box}) or None (empty), cols x rows of them (None: the cameras, in a grid just big enough). background:
    the stream's colour, behind everything. turns_file: the timetable
    of taking turns (timetable()), when the cameras take turns. The words
    under each camera (a file per camera; None: no words); taking turns ((seconds on the whole grid, on each camera), and
    the timetable's file; None: the grid all the time); the border's colour round each square; the resolution.
    """

    status_files: list[str] | None = None
    cycle: tuple[int, int] | None = None
    turns_file: str | None = None
    resolution: str = DEFAULT_RESOLUTION  # one of RESOLUTIONS
    border_color: str = DEFAULT_BORDER
    background: str = DEFAULT_BACKGROUND
    clock: float = 0  # the time of day (seconds since 1970) at the stream's start: slideshows and turns count from it
    encoder: str = "cpu"  # "cpu" (libx264) or "nvenc" (an NVIDIA card's own encoder; see runner.encoder)
    font: str | None = None  # the stream's words, unless a square has its own (None: DEFAULT_FONT)
    color: str | None = None  # (None: DEFAULT_TEXT_COLOR)
    cols: int | None = None
    rows: int | None = None
    cells: list | None = None


# How the picture is compressed for sending: on the processor (libx264, fast settings for live), or on an NVIDIA card's
# own video encoder (NVENC), which leaves the processor to read the cameras and lay out the grid. Both send H.264 at
# the same bitrate, so YouTube and Twitch see the same stream.
ENCODERS = {
    "cpu": ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency"],
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "ll", "-rc", "cbr"],
}


def encoder_args(encoder: str) -> list[str]:
    return list(ENCODERS.get(encoder, ENCODERS["cpu"]))


def command(ffmpeg: str, srcs: list[Source], url: str, look: Look | None = None) -> list[str]:
    """
    The whole ffmpeg command: the grid's squares laid out, each camera turned as Mainsail shows it and fitted into its
    square with the printer and its print written along its foot; each card its colour, its picture (or slideshow,
    each picture over the first in its own seconds) fitted over it and its words over that; an empty square the stream's
    background colour; every square with a border round it; a silent sound track; sent as FLV to `url`.

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
    width, height, kbps = RESOLUTIONS.get(look.resolution, RESOLUTIONS[DEFAULT_RESOLUTION])
    k = height / 720  # the words and borders grow with the picture
    px = lambda v: max(1, round(v * k))  # noqa: E731
    tw, th = (width // cols) // 2 * 2, (height // rows) // 2 * 2
    edge = px(BORDER_WIDTH)
    border = f"drawbox=x=0:y=0:w=iw:h=ih:color=0x{(look.border_color or DEFAULT_BORDER).lstrip('#')}:t={edge}"
    back = (look.background or DEFAULT_BACKGROUND).lstrip("#")
    full_size = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x{back},setsar=1"

    args = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin"]
    for s in srcs:
        args += ["-thread_queue_size", "64", *s.input_args]
    args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    extra = n + 1  # the next input's number: each picture shown is an input of its own, read once a second

    def picture(path: str) -> int:
        nonlocal args, extra
        args += ["-loop", "1", "-framerate", "1", "-i", path]
        extra += 1
        return extra - 1

    def card(c: int, cd: dict) -> str:
        """A card's square: its colour; its pictures fitted over it, each but the first only in its own seconds (each
        read and fitted once a second); its words over that (on a dark band when chosen)."""
        chain = [f"color=c=0x{(cd.get('background') or '#' + back).lstrip('#')}:s={tw}x{th}:r={FPS},setsar=1[c{c}b]"]
        shown = f"[c{c}b]"
        paths, seconds = cd.get("pictures") or [], cd.get("seconds") or SLIDE_SECONDS[2]
        period = len(paths) * seconds
        # the picture's box is a part of the square inside its border, so the border never covers the picture; a
        # slideshow's picture resized or moved on its own has its own box (picture_boxes, by its file's name)
        iw, ih = tw - 2 * edge, th - 2 * edge
        own_boxes = cd.get("picture_boxes") or {}

        def fit(path: str) -> tuple[int, int, str]:
            pb = _picture_box(own_boxes.get(os.path.basename(path)) or cd.get("picture_box"))
            bw, bh = max(2, round(pb["w"] * iw)), max(2, round(pb["h"] * ih))
            bx, by = edge + round(pb["x"] * iw), edge + round(pb["y"] * ih)
            return bw, bh, "(W-w)/2:(H-h)/2" if (bw, bh) == (iw, ih) else f"{bx}+({bw}-w)/2:{by}+({bh}-h)/2"
        # the slideshow's time: counted from midnight 1970 (look.clock at the start), as the page counts it
        lag = round(look.clock % period, 3) if period else 0
        t = f"t+{lag:g}" if lag else "t"

        def window(j: int) -> str:  # while picture j is on show
            return f"gte(mod({t},{period}),{j * seconds})*lt(mod({t},{period}),{(j + 1) * seconds})"

        blanks = any(stream_media.is_blank(p) for p in paths)  # then even the first picture shows only in its turn
        for j, path in enumerate(paths):
            if stream_media.is_blank(path):  # a blank screen: the square's colour (and its words) in its turn
                continue
            bw, bh, at = fit(path)
            chain.append(f"[{picture(path)}:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease,setsar=1,fps={FPS}[c{c}i{j}]")
            when = "" if j == 0 and not blanks else f":enable='{window(j)}'"
            chain.append(f"{shown}[c{c}i{j}]overlay={at}{when}[c{c}o{j}]")
            shown = f"[c{c}o{j}]"
        last = []

        def words(file: str, tb: dict, enable: str = "") -> str:
            big = round(tb["size"] * th)
            band = f":box=1:boxcolor=black@0.5:boxborderw={max(px(4), big // 5)}" if cd.get("band") else ""
            return (f"drawtext=fontfile={_filter_path(font_file(cd.get('font') or look.font))}:textfile={_filter_path(file)}:reload=1:expansion=none"
                    f":fontsize={max(px(10), big)}:fontcolor=0x{(cd.get('color') or look.color or DEFAULT_TEXT_COLOR).lstrip('#')}:line_spacing={big // 4}"
                    f":x={round(tb['x'] * tw)}-text_w/2:y={round(tb['y'] * th)}-text_h/2{band}{enable}")

        own = cd.get("picture_words") or {}  # a slideshow's pictures' own words, by their place in it
        if cd.get("words"):
            tb = _text_box(cd.get("text_box"), cd.get("size"), cd.get("position"))
            rest = [j for j in range(len(paths)) if j not in own]
            if not own:
                last.append(words(cd["words"], tb))
            elif rest:  # the card's words over the pictures without words of their own
                last.append(words(cd["words"], tb, f":enable='{'+'.join(window(j) for j in rest)}'"))
        for j, cap in sorted(own.items()):
            last.append(words(cap["words"], _text_box(cap.get("text_box")), f":enable='{window(j)}'" if len(paths) > 1 else ""))
        last.append(border)
        chain.append(f"{shown}{','.join(last)}[c{c}]")
        return ";".join(chain)

    # the words under a camera, sized to its square (20 px in a quarter of a 720p picture)
    small = max(px(11), min(th // 18, tw // 32))
    # each camera's own square choices, by its place in srcs: ("camera", place, its cell or just its colour (tests))
    camera_own = {}
    for cell in cells or []:
        if cell and cell[0] == "camera" and len(cell) > 2 and cell[2]:
            camera_own[cell[1]] = cell[2] if isinstance(cell[2], dict) else {"background": cell[2]}
    # a camera's words in its own font and colour, else the stream's
    stream_words = {k: v for k, v in (("words_font", look.font), ("words_color", look.color)) if v}
    camera_own = {i: {**stream_words, **{k: v for k, v in own.items() if v is not None}} for i, own in camera_own.items()}
    foot, left = small * 2 // 3 + edge, small // 2 + edge
    parts = []
    for i, s in enumerate(srcs):
        base = ",".join([*s.turn, "setpts=PTS-STARTPTS", f"fps={FPS}", "setsar=1"])
        outs = ([f"[g{i}]"] if need_grid else []) + ([f"[s{i}]"] if cycle else [])
        parts.append(f"[{i}:v]{base}" + (f",split=2{''.join(outs)}" if len(outs) == 2 else outs[0]))
    if need_grid:
        tiles = []
        for c, cell in enumerate(cells):
            if cell and cell[0] == "camera":
                i = cell[1]
                mine = camera_own.get(i, stream_words)
                colour = (mine.get("background") or "#" + back).lstrip("#")  # the square's own colour round it
                chain = [f"scale={tw}:{th}:force_original_aspect_ratio=decrease", f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=0x{colour}"]
                if look.status_files and mine.get("show_words", True):
                    if mine.get("words_size"):
                        size = max(px(8), round(mine["words_size"] * th))
                        chain.append(_words(look.status_files[i], size, size * 2 // 3 + edge, max(2, size // 3), size // 2 + edge, mine))
                    else:
                        chain.append(_words(look.status_files[i], small, foot, px(6), left, mine))
                parts.append(f"[g{i}]{','.join(chain)},{border}[c{c}]")
            elif cell and cell[0] == "card":
                parts.append(card(c, cell[1]))
            else:
                parts.append(f"color=c=0x{back}:s={tw}x{th}:r={FPS},setsar=1,{border}[c{c}]")
            tiles.append(f"[c{c}]")
        if len(tiles) == 1:
            parts.append(f"{tiles[0]}{full_size}[grid]")
        else:
            layout = "|".join(f"{(c % cols) * tw}_{(c // cols) * th}" for c in range(len(tiles)))
            parts.append(f"{''.join(tiles)}xstack=inputs={len(tiles)}:layout={layout}:fill=0x{back},{full_size}[grid]")
    if cycle is None:
        video = "[grid]"
    else:
        picked = ""
        for i in range(n):
            if look.status_files:
                mine = camera_own.get(i, stream_words)
                if not mine.get("show_words", True):
                    picked += f"[s{i}]"
                    continue
                full = FULL_WORDS
                if mine.get("words_size"):  # its own size, as part of the camera's own picture's height
                    f = mine["words_size"]
                    full = {"size": f"h*{f}", "foot": f"h*{f * 2 / 3:.4f}", "border": f"h*{f / 3:.4f}", "left": f"h*{f / 2:.4f}"}
                parts.append(f"[s{i}]{_words(look.status_files[i], **full, own=mine)}[w{i}]")
                picked += f"[w{i}]"
            else:
                picked += f"[s{i}]"
        parts.append(f"{picked}streamselect@pick=inputs={n}:map=0,{full_size}[full]")
        parts.append(f"[grid][full]streamselect@view=inputs=2:map=0[turns]" if need_grid else "[full]null[turns]")
        video = "[turns]"
    if look.turns_file:  # the timetable moves the switches of taking turns
        parts.append(f"{video}sendcmd=f={_filter_path(look.turns_file)}[timed]")
        video = "[timed]"
    args += ["-filter_complex", ";".join(parts), "-map", video, "-map", f"{n}:a"]
    args += [*encoder_args(look.encoder), "-pix_fmt", "yuv420p", "-r", str(FPS),
             "-g", str(FPS * 2), "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
    if look.turns_file:
        args += ["-t", str(TURNS_FOR)]
    args += ["-f", "flv", url]
    return args


def status_line(label: str, p: dict) -> str:
    """What's written under a camera: "VT 1190 · Printing 42% · benchy.gcode", "VT 1190 · Idle", or "VT 1190 · Status
    unknown" when the printer couldn't be asked (not answering, or refusing Farmhand's login)."""
    if p.get("state"):
        pct = p.get("progress")
        line = f"{label} · {'Paused' if p['state'] == 'paused' else 'Printing'}"
        if isinstance(pct, (int, float)):
            line += f" {round(pct)}%"
        if p.get("file"):
            line += f" · {os.path.basename(str(p['file']))[:60]}"
        return line
    if p.get("error"):
        return f"{label} · Status unknown"
    return f"{label} · Idle"
