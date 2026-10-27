"""
Which printer a sliced G-code was made for: the same physical_printer_settings_id a PrusaSlicer 3MF carries, read
from the settings PrusaSlicer writes into the G-code itself.

  .gcode   the settings are "; key = value" comment lines in a block at the very end of the file
  .bgcode  Prusa's binary G-code: a list of blocks, one of them the slicer's settings ("key=value" lines), kept
           as-is or deflate-compressed. Only the block headers are read on the way to it, never the moves.

Anything not found (another slicer, no physical printer picked, an unreadable file) answers None: then there's
nothing to check against, and the G-code is taken as it is.
"""
from __future__ import annotations

import re
import struct
import zlib

_KEY = "physical_printer_settings_id"
_TAIL = 1024 * 1024  # PrusaSlicer's settings block is well under this; it's always the last thing in a .gcode
# the value is the rest of that one line (it may be empty: no physical printer was picked)
_TEXT_RE = re.compile(rb"^;[ \t]*" + _KEY.encode() + rb"[ \t]*=([^\r\n]*)", re.MULTILINE)
_BINARY_RE = re.compile(rb"^[ \t]*" + _KEY.encode() + rb"[ \t]*=([^\r\n]*)", re.MULTILINE)

# .bgcode layout: "GCDE", version (u32), checksum type (u16); then blocks of: type (u16), compression (u16),
# uncompressed size (u32), compressed size (u32, only when compressed), parameters, data, checksum
_SLICER_METADATA = 2
_THUMBNAIL = 5
_NO_COMPRESSION, _DEFLATE = 0, 1


def printer_profile(file_obj, filename: str | None) -> str | None:
    """The printer profile a .gcode or .bgcode was sliced for, or None. The file is left at its start."""
    try:
        if (filename or "").lower().endswith(".bgcode"):
            return _from_bgcode(file_obj)
        return _from_gcode(file_obj)
    except (OSError, ValueError, struct.error, zlib.error):
        return None
    finally:
        file_obj.seek(0)


def _found(m: re.Match | None) -> str | None:
    value = m.group(1).decode("utf-8", "replace").strip().strip('"') if m else ""
    return value or None


def _from_gcode(f) -> str | None:
    f.seek(0, 2)
    f.seek(max(0, f.tell() - _TAIL))
    return _found(_TEXT_RE.search(f.read()))


def _from_bgcode(f) -> str | None:
    f.seek(0)
    head = f.read(10)
    if len(head) < 10 or head[:4] != b"GCDE":
        return None
    checksum_size = 4 if struct.unpack("<H", head[8:10])[0] == 1 else 0  # 1 = CRC32
    while True:
        block = f.read(8)
        if len(block) < 8:
            return None
        kind, compression, size = struct.unpack("<HHI", block)
        stored = struct.unpack("<I", f.read(4))[0] if compression != _NO_COMPRESSION else size
        params = 6 if kind == _THUMBNAIL else 2
        if kind != _SLICER_METADATA:
            f.seek(params + stored + checksum_size, 1)
            continue
        f.seek(params, 1)
        data = f.read(stored)
        if compression == _DEFLATE:
            try:
                data = zlib.decompress(data)  # zlib-wrapped, as libbgcode writes it
            except zlib.error:
                data = zlib.decompress(data, -15)  # or bare deflate
        elif compression != _NO_COMPRESSION:
            return None  # heatshrink: not used for settings by PrusaSlicer, and not worth a dependency
        return _found(_BINARY_RE.search(data))
