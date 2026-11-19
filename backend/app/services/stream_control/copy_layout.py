"""
Copy layout: one stream plugin's own layout made Stream control's, so every stream brought in shows it. Farmhand asks
the plugin where it runs for its own page's set-up (GET <address>/api/stream: {settings, media}: the YouTube and Twitch
plugins' own, never Stream control's design they may be following), takes the layout part of its settings (the grid
and squares, taking turns, size, colours, words, music choices, holding screen, delay, title and description) into the
design, and copies the pictures it shows into Farmhand's stream folder: single pictures, and each slideshow it shows
with its pictures and order. The music's tracks aren't copied (they can be large): add them on Stream control's page.

A picture already in Farmhand's stream folder under the same name is kept as it is.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from ... import storage
from ..plugins import registry, remote
from . import design, media, nas_copy, streams
from .fonts import FONTS


def enc(name: str) -> str:
    """A file name as it goes in a URL path."""
    return quote(name, safe="")


PAGE_PATH = streams.PAGE_PATH
TIMEOUT = 15.0
# What of a plugin's own settings is the layout (design.SAVED): the rest (its stream key, site settings) stays its own
LAYOUT_KEYS = design.SAVED


def _get(client: httpx.Client, url: str) -> httpx.Response:
    try:
        return client.get(url)
    except httpx.HTTPError as e:
        raise ValueError(remote.unreachable(url.split("/api/")[0], e)) from None


def _pictures_shown(settings: dict) -> tuple[set[str], set[str]]:
    """(single pictures' names, slideshows' names) the layout shows: squares' own pictures, their more pictures (also a
    slideshow screen's), and the holding screen's picture."""
    images, shows = set(), set()
    for cell in settings.get("cells") or []:
        if not isinstance(cell, dict) or "camera" in cell:
            continue
        if isinstance(cell.get("image"), str) and cell["image"]:
            images.add(cell["image"])
        if isinstance(cell.get("slideshow"), str) and cell["slideshow"]:
            shows.add(cell["slideshow"])
        layers = list(cell.get("layers") or [])
        for more in (cell.get("slide_layers") or {}).values():
            layers += more if isinstance(more, list) else []
        for layer in layers:
            if isinstance(layer, dict) and layer.get("type") == "picture" and isinstance(layer.get("image"), str) and layer["image"]:
                images.add(layer["image"])
    holding = settings.get("holding") if isinstance(settings.get("holding"), dict) else {}
    if isinstance(holding.get("image"), str) and holding["image"]:
        images.add(holding["image"])
    return images, shows


def _copy_file(client: httpx.Client, url: str, target: Path, copied: list[str], problems: list[str], label: str) -> None:
    if target.exists():
        return  # (one of that name is here already: kept)
    r = _get(client, url)
    if r.status_code != 200:
        problems.append(f"{label} couldn't be copied (the plugin answered {r.status_code}).")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    storage.write_bytes_atomically(target, r.content)
    copied.append(label)


def copy_from(db: Session, plugin_id: str) -> dict:
    """
    Make this stream plugin's own layout Stream control's, its pictures and slideshows copied over:
    {copied: [what was copied], problems: [plain words], design}. ValueError when it can't be asked or answers no layout.
    """
    plugin = registry.get(db, plugin_id)
    if not streams.control_of(plugin):
        raise ValueError(f"{plugin.name} isn't a stream plugin, so it has no layout to copy.")
    if not plugin.enabled:
        raise ValueError(f"{plugin.name} is switched off. Switch it on on the Plugins page first.")
    address = registry.connection_of(plugin).address
    with httpx.Client(transport=remote.transport, timeout=TIMEOUT, follow_redirects=False) as client:
        r = _get(client, f"{address}{PAGE_PATH}")
        try:
            page = r.json() if r.status_code == 200 else None
        except ValueError:
            page = None
        settings = page.get("settings") if isinstance(page, dict) else None
        if not isinstance(settings, dict) or not isinstance(settings.get("cells"), list):
            raise ValueError(f"{plugin.name} didn't answer with a layout (it answered {r.status_code}). Is it the YouTube or Twitch plugin?")
        theirs = page.get("media") if isinstance(page.get("media"), dict) else {}

        sent = {k: settings[k] for k in LAYOUT_KEYS if k in settings}
        if sent.get("font") not in FONTS:
            sent.pop("font", None)  # (a font the plugin knows but Farmhand doesn't: Stream control's own stays)
        new = design.save(db, sent)

        copied: list[str] = []
        problems: list[str] = []
        try:
            folder = media.folder(db, make=True)
        except storage.StorageUnavailableError as e:
            problems.append(f"The pictures weren't copied: {e}")
            media.forget(at_once=True)
            return {"copied": copied, "problems": problems, "design": new}
        images, shows = _pictures_shown(settings)
        for name in sorted(images):
            try:
                target = folder / media.IMAGES / media.checked_name(name, "picture")
            except ValueError:
                continue
            _copy_file(client, f"{address}{PAGE_PATH}/pictures/{enc(name)}", target, copied, problems, f"the picture “{name}”")
        their_shows = {s.get("name"): s.get("images") or [] for s in theirs.get("slideshows") or [] if isinstance(s, dict)}
        for show in sorted(shows):
            if show not in their_shows:
                problems.append(f"The slideshow “{show}” isn't in {plugin.name}'s stream folder, so it wasn't copied.")
                continue
            try:
                show_dir = folder / media.SLIDESHOWS / media.checked_name(show, "slideshow")
            except ValueError:
                continue
            order = [n for n in their_shows[show] if isinstance(n, str)]
            for name in order:
                if media.is_blank(name):
                    continue
                _copy_file(client, f"{address}{PAGE_PATH}/slideshows/{enc(show)}/pictures/{enc(name)}",
                           show_dir / media.checked_name(name, "picture"), copied, problems, f"“{show}”: “{name}”")
            show_dir.mkdir(parents=True, exist_ok=True)
            if not (show_dir / media.ORDER_FILE).exists():
                media.write_order(show_dir, order)
    media.forget(at_once=True)
    nas_copy.changed()  # (the pictures copied in: on the NAS copy soon)
    if settings.get("music") is not False and (theirs.get("music") or []):
        problems.append(f"{plugin.name}'s music tracks weren't copied: add them under Music on this page.")
    return {"copied": copied, "problems": problems, "design": new}
