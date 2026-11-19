"""
Stream control's pictures, slideshows and music are worked from a copy of Farmhand's own (WORKING, on Farmhand's own
disk), and kept in step with the stream folder beside the STL folder (on the NAS, when that's where the files are),
which stays the copy people see and copy files into by hand. So the page and the stream plugins never wait on the NAS:
a NAS that's slow or away only holds up the copying, never the stream.

Kept in step both ways, in the background (CopyWorker: soon after a change made through Farmhand, else every EVERY
seconds; and when Scan folder is pressed or the design saved):

- a file added, replaced or taken out through Farmhand is copied to the NAS, or taken out of it;
- a file added or replaced on the NAS by hand is copied in, and one taken out there by hand is taken out here too.

Which side changed is told by what each file was when the two were last the same (STATE, in the working copy: each
file's size and modified time on each side). A file changed on both sides since: the newer wins. Only the stream
folder's own files are ever copied or taken out (pictures, slideshows' pictures and their order, music): nothing
else in it is touched, and a slideshow's folder is only taken out once nothing else is left in it.

Until the first copying from the NAS has finished (after updating to this, or on a new disk), Stream control goes on
working from the NAS folder itself, as it did before, so the stream plugins never see the folder half there.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ... import storage
from ...database import SessionLocal
from ...periodic import PeriodicWorker

log = logging.getLogger("farmhand")

WORKING = ("stream-control", "stream")  # under Farmhand's own storage folder
STATE = ".farmhand-nas-copy.json"  # in the working copy: {"nas": its path, "files": {rel: [size, here_ns, nas_ns]}, "done": bool}
EVERY = 60  # seconds between looks at the NAS folder when nothing changed through Farmhand
SOON = 3  # seconds after a change through Farmhand that it's copied
# A NAS folder found with none of the files it had, while there were at least this many: taken as one that isn't the
# right folder or isn't all there (not as everything having been deleted by hand), so nothing is taken out here
LOOKS_EMPTIED = 3

_lock = threading.Lock()  # one copying at a time
_status = {"copied_at": None, "error": None, "copying": False}
_wake = threading.Event()


def working_root() -> Path:
    return storage.local_root().joinpath(*WORKING)


def nas_root() -> Path:
    """The stream folder beside the STL folder (on the NAS, when that's where the files are): StorageUnavailableError
    while it can't be used (its share unmounted, say)."""
    from .media import FOLDER_NAME

    return storage.named_folder(storage.ready_root("stl").parent, FOLDER_NAME)


def nas_root_named() -> Path:
    """Where the NAS folder is, whether or not it can be used now (for the page)."""
    from .media import FOLDER_NAME

    return storage.named_folder(storage.effective_root("stl").parent, FOLDER_NAME)


def _state() -> dict:
    try:
        got = json.loads((working_root() / STATE).read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def ready() -> bool:
    """The working copy has been filled from the NAS folder once: Stream control works from it."""
    return bool(_state().get("done"))


def status() -> dict:
    """{working (Stream control works from Farmhand's own copy), copied_at (when the NAS was last in step), error (why
    it couldn't be, or None), copying, waiting (changes made through Farmhand not on the NAS yet)}."""
    return {"working": ready(), **_status, "waiting": _wake.is_set()}


def changed() -> None:
    """Something was changed through Farmhand: copied to the NAS soon."""
    _wake.set()


# ------------------------------------------------------------------ copying


def _files(root: Path) -> dict[str, tuple[int, int]]:
    """The stream folder's own files: {"images/logo.png": (size, modified ns), "slideshows/Prints/a.jpg": ...,
    "slideshows/Prints/.farmhand-order.json": ..., "music/beat.mp3": ...}, plus each slideshow's folder ("slideshows/Prints/":
    (-1, 0))."""
    from .media import IMAGES, MUSIC, ORDER_FILE, PICTURE_TYPES, SLIDESHOWS, TRACK_TYPES

    out: dict[str, tuple[int, int]] = {}

    def add(d: Path, prefix: str, types: dict, order: bool = False) -> None:
        try:
            entries = list(os.scandir(d))
        except OSError:
            return
        for e in entries:
            try:
                if not e.is_file():
                    continue
                if not ((Path(e.name).suffix.lower() in types and not e.name.startswith(".")) or (order and e.name == ORDER_FILE)):
                    continue
                st = e.stat()
            except OSError:
                continue
            out[prefix + e.name] = (st.st_size, st.st_mtime_ns)

    add(root / IMAGES, f"{IMAGES}/", PICTURE_TYPES)
    add(root / MUSIC, f"{MUSIC}/", TRACK_TYPES)
    try:
        shows = [e for e in os.scandir(root / SLIDESHOWS) if e.is_dir() and not e.name.startswith(".")]
    except OSError:
        shows = []
    for s in shows:
        out[f"{SLIDESHOWS}/{s.name}/"] = (-1, 0)
        add(Path(s.path), f"{SLIDESHOWS}/{s.name}/", PICTURE_TYPES, order=True)
    return out


def _copy(source: Path, target: Path) -> None:
    """A file copied whole or not at all (under a temporary name, then renamed), keeping its modified time, so the
    stream plugins' stamps of it stay the same whichever copy they're read from."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        shutil.copyfile(source, part)
        st = source.stat()
        os.utime(part, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _take_out(root: Path, rel: str) -> None:
    """One of the stream folder's own files taken out; a slideshow's folder only once nothing at all is left in it."""
    path = root / rel
    if rel.endswith("/"):
        try:
            path.rmdir()
        except OSError:
            pass  # (something else is in it, or it's gone: left as it is)
    else:
        path.unlink(missing_ok=True)


def sync(db: Session | None = None) -> dict:
    """The working copy and the NAS folder brought in step (see the module's notes): {copied_in, copied_out,
    taken_out_here, taken_out_there}. StorageUnavailableError while the NAS folder can't be used; OSError when copying
    failed part-way (what was copied stays copied, and is remembered)."""
    with _lock:
        _status["copying"] = True
        _wake.clear()
        try:
            done = _sync()
            _status["copied_at"], _status["error"] = datetime.now(timezone.utc).isoformat(), None
            return done
        except (storage.StorageUnavailableError, OSError) as e:
            _status["error"] = str(e) if isinstance(e, storage.StorageUnavailableError) else f"Copying failed: {e.strerror or e}"
            raise
        finally:
            _status["copying"] = False


def _sync() -> dict:
    nas = nas_root()
    here = working_root()
    here.mkdir(parents=True, exist_ok=True)
    state = _state()
    if state.get("nas") != str(nas):  # (first time, or the stream folder is another one now: no deletions either way)
        state = {"nas": str(nas), "files": {}, "done": False}
    last: dict[str, list] = state.get("files") or {}
    from .media import IMAGES, MUSIC, SLIDESHOWS

    for d in (IMAGES, SLIDESHOWS, MUSIC):  # (both made, with their folders: each there to copy into by hand)
        for root in (here, nas):
            try:
                (root / d).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass  # (a read-only share: what's there is still copied in)
    mine, theirs = _files(here), (_files(nas) if nas.is_dir() else {})
    counts = {"copied_in": 0, "copied_out": 0, "taken_out_here": 0, "taken_out_there": 0}
    emptied = not theirs and len(last) >= LOOKS_EMPTIED
    if emptied:
        log.warning("The NAS stream folder %s has none of the %d files it had: nothing is taken out of Farmhand's copy", nas, len(last))

    def save() -> None:
        storage.write_text_atomically(here / STATE, json.dumps(state))

    # (each slideshow's folder after its files, so one emptied is taken out once its files are)
    for rel in sorted(set(mine) | set(theirs) | set(last), key=lambda r: (r.endswith("/"), r)):
        a, b, was = mine.get(rel), theirs.get(rel), last.get(rel)
        if a and b and not rel.endswith("/") and a == b:  # the same file on both sides (found so the first time)
            last[rel] = [a[0], a[1], b[1]]
            continue
        here_changed = a is not None and (was is None or [a[0], a[1]] != [was[0], was[1]])
        there_changed = b is not None and (was is None or [b[0], b[1]] != [was[0], was[2]])
        if rel.endswith("/"):  # a slideshow's folder
            if a and not b and (was is None or emptied):
                (nas / rel).mkdir(parents=True, exist_ok=True)
            elif b and not a and was is None:
                (here / rel).mkdir(parents=True, exist_ok=True)
            elif was and not a and b:
                _take_out(nas, rel)
            elif was and not b and a and not emptied:
                _take_out(here, rel)
            if (here / rel).is_dir() and (nas / rel).is_dir():
                last[rel] = [-1, 0, 0]
            else:
                last.pop(rel, None)
            continue
        if a and b and not here_changed and not there_changed:
            continue
        if a and (not b or (here_changed and (not there_changed or a[1] >= b[1]))) and not (not b and was and not emptied):
            _copy(here / rel, nas / rel)
            counts["copied_out"] += 1
        elif b and (not a or there_changed) and not (not a and was):
            _copy(nas / rel, here / rel)
            counts["copied_in"] += 1
        elif not a and b and was:  # taken out through Farmhand
            _take_out(nas, rel)
            counts["taken_out_there"] += 1
            last.pop(rel, None)
            continue
        elif a and not b and was and not emptied:  # taken out on the NAS by hand
            _take_out(here, rel)
            counts["taken_out_here"] += 1
            last.pop(rel, None)
            continue
        else:
            last.pop(rel, None)
            continue
        sa, sb = (here / rel).stat(), (nas / rel).stat()
        last[rel] = [sa.st_size, sa.st_mtime_ns, sb.st_mtime_ns]
        state["files"] = last
        save()  # (after each file: copying that fails part-way is picked up where it stopped)
    # the folders the slideshows had, gone from both sides: forgotten
    for rel in [r for r in last if r.endswith("/") and not (here / r).is_dir() and not (nas / r).is_dir()]:
        last.pop(rel)
    state["files"], state["done"] = last, True
    save()
    if any(counts.values()):
        from . import media

        media.forget(at_once=True)
        log.info("Stream control's folder and the NAS copy brought in step: %s", counts)
    return counts


def sync_quietly() -> dict | None:
    """sync(), what went wrong only remembered (status()) and logged."""
    try:
        return sync()
    except (storage.StorageUnavailableError, OSError) as e:
        log.info("Stream control's folder couldn't be copied to or from the NAS: %s", e)
        return None


class CopyWorker(PeriodicWorker):
    name, failure, log = "stream-nas-copy", "Copying Stream control's folder to or from the NAS failed", log

    def __init__(self):
        super().__init__(interval=SOON, first_wait=5)
        self._last = 0.0

    def run_once(self) -> None:
        if _wake.is_set() or time.monotonic() - self._last >= EVERY or not ready():
            self._last = time.monotonic()
            sync_quietly()


worker = CopyWorker()
