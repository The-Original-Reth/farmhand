"""
The little of Farmhand's storage the stream folder needs: writing a file whole or not at all, and saying the folder
can't be used now (an unmounted NAS share, say).
"""
from __future__ import annotations

import os
from pathlib import Path


class StorageUnavailableError(RuntimeError):
    """The stream folder isn't there or can't be written now (503)."""


def _write_whole(target: Path, data: bytes) -> None:
    temp = target.with_name(f".{target.name}.farmhand-part")
    try:
        temp.write_bytes(data)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def write_text_atomically(target, text: str) -> None:
    _write_whole(Path(target), text.encode("utf-8"))


def write_bytes_atomically(target, data: bytes) -> None:
    _write_whole(Path(target), data)
