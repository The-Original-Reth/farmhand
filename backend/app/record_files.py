"""
What every file Farmhand keeps on the NAS about itself has in common: the settings file (config_store), the printer
and model files beside it (records_store), and the records beside the files themselves (project_records,
library_records). How they're written (JSON, atomically), read (capped in size, unreadable ones passed over), how they
name files and times, and the background writer that writes them after a change without holding up the page.

The text they write must never change for the same contents: records_store compares it with what's on the NAS to
skip rewriting a file that's already right.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
from pathlib import Path
from typing import Callable

from . import storage

log = logging.getLogger("farmhand.record_files")


# ------------------------------------------------------------------ writing and reading


def dumps(document: dict) -> str:
    """A document's text, as every one of Farmhand's files has it."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_json(path: str | os.PathLike, document: dict) -> None:
    """Written atomically: a share dropping mid-write must never leave half a file."""
    storage.write_text_atomically(Path(path), dumps(document))


def read_json(path: str | os.PathLike, max_bytes: int):
    """The file's JSON, or None when it can't be read, isn't JSON, or is too large to be one of Farmhand's."""
    path = Path(path)
    try:
        if path.stat().st_size > max_bytes:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def names_in(folder: str | os.PathLike, prefix: str) -> list[str]:
    """The names of the JSON files in a folder that start with `prefix` (none when the folder can't be read)."""
    try:
        return [n for n in os.listdir(folder) if n.startswith(prefix) and n.endswith(".json")]
    except OSError:
        return []


def newest_first(docs: list, saved_at: Callable[[object], object] = lambda d: d) -> list:
    """Records sorted by their "saved_at", the newest first (one without comes last)."""
    def key(item):
        when = saved_at(item).get("saved_at")
        return when if isinstance(when, str) else ""
    return sorted(docs, key=key, reverse=True)


# ------------------------------------------------------------------ times and places


def stamp() -> str:
    """Now, as a file says when it was saved: "2026-11-07T22:48:33+00:00"."""
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def iso_or_none(value) -> str | None:
    """A time as a record keeps it (as the database has it), or None."""
    return value.isoformat() if isinstance(value, dt.datetime) else None


def parse_iso(value) -> dt.datetime | None:
    """A time read back from a record, or None when it isn't one."""
    try:
        return dt.datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def relative_to(path: str | None, base: Path) -> str | None:
    """A file's place in a record: relative to `base` when it's inside it (so the record still holds when the share is
    mounted somewhere else), else as it is."""
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path


def resolve_from(base: Path, where) -> Path | None:
    """A file named in a record: relative to `base`, or as it was written when it's a whole path."""
    if not isinstance(where, str) or not where:
        return None
    p = Path(where)
    return p if p.is_absolute() else base / p


# ------------------------------------------------------------------ writing in the background


class BackgroundWriter:
    """
    Writes records after a change on a thread of its own, so a slow NAS never holds up the page. Off until the app
    starts it (tests write records themselves). A folder that's away is passed over: the records are written again with
    the next change, or when Farmhand starts. Any other failure is logged, never raised.
    """

    def __init__(self, name: str, what: str):
        self.name, self.what, self.enabled = name, what, False

    def enable(self) -> None:
        self.enabled = True

    def run(self, write: Callable) -> None:
        """Run `write(db)` with a session of its own, in the background."""
        if not self.enabled:
            return
        from .database import SessionLocal

        def go():
            try:
                with SessionLocal() as db:
                    write(db)
            except storage.StorageUnavailableError:
                pass
            except Exception:  # noqa: BLE001 - a record failing must never take anything down
                log.exception("Writing %s failed", self.what)

        threading.Thread(target=go, name=self.name, daemon=True).start()
