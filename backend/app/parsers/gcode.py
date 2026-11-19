"""
Which printer a sliced G-code was made for: the same physical_printer_settings_id a PrusaSlicer 3MF carries, read
from the settings PrusaSlicer writes into the G-code itself.

  .gcode   the settings are "; key = value" comment lines in a block at the very end of the file
  .bgcode  Prusa's binary G-code: a list of blocks, one of them the slicer's settings ("key=value" lines), kept
           as-is or deflate-compressed. Only the block headers are read on the way to it, never the moves.

Anything not found (another slicer, no physical printer picked, an unreadable file) answers None: then there's
nothing to check against, and the G-code is taken as it is.

And the filament settings the slicer wrote (filament_settings): its price per kg, density and diameter, from the
same settings block, for costing a print as Mainsail's G-codes are (services/filament_cost.py).

And the slicer's own estimate of the filament a G-code uses (slicer_filament): "filament used [mm]", "[g]" and
"filament cost", which PrusaSlicer writes as "; key = value" comments near the end of a .gcode, and in a .bgcode's
printer and print metadata blocks (which come before the moves).
"""
from __future__ import annotations

import math
import re
import struct
import zlib

GCODE_EXTENSIONS = (".gcode", ".bgcode")  # plain G-code, and Prusa's binary G-code

_KEY = "physical_printer_settings_id"
_TAIL = 1024 * 1024  # PrusaSlicer's settings block is well under this; it's always the last thing in a .gcode
# the value is the rest of that one line (it may be empty: no physical printer was picked)
_TEXT_RE = re.compile(rb"^;[ \t]*" + _KEY.encode() + rb"[ \t]*=([^\r\n]*)", re.MULTILINE)
_BINARY_RE = re.compile(rb"^[ \t]*" + _KEY.encode() + rb"[ \t]*=([^\r\n]*)", re.MULTILINE)

# .bgcode layout: "GCDE", version (u32), checksum type (u16); then blocks of: type (u16), compression (u16),
# uncompressed size (u32), compressed size (u32, only when compressed), parameters, data, checksum
_GCODE, _SLICER_METADATA, _PRINTER_METADATA, _PRINT_METADATA, _THUMBNAIL = 1, 2, 3, 4, 5
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
    return _found(_TEXT_RE.search(_tail(f)))


def _tail(f) -> bytes:
    f.seek(0, 2)
    f.seek(max(0, f.tell() - _TAIL))
    return f.read()


def _from_bgcode(f) -> str | None:
    for _, data in _bgcode_blocks(f, {_SLICER_METADATA}):
        return _found(_BINARY_RE.search(data))
    return None


def _bgcode_blocks(f, kinds: set[int]):
    """The data of each block of these kinds in a .bgcode, in file order. Only block headers are read on the way, and
    it stops at the first G-code block: the metadata blocks all come before the moves."""
    f.seek(0)
    head = f.read(10)
    if len(head) < 10 or head[:4] != b"GCDE":
        return
    checksum_size = 4 if struct.unpack("<H", head[8:10])[0] == 1 else 0  # 1 = CRC32
    while True:
        block = f.read(8)
        if len(block) < 8:
            return
        kind, compression, size = struct.unpack("<HHI", block)
        if kind == _GCODE:
            return
        stored = struct.unpack("<I", f.read(4))[0] if compression != _NO_COMPRESSION else size
        params = 6 if kind == _THUMBNAIL else 2
        if kind not in kinds:
            f.seek(params + stored + checksum_size, 1)
            continue
        f.seek(params, 1)
        data = f.read(stored)
        f.seek(checksum_size, 1)
        if compression == _DEFLATE:
            try:
                data = zlib.decompress(data)  # zlib-wrapped, as libbgcode writes it
            except zlib.error:
                data = zlib.decompress(data, -15)  # or bare deflate
        elif compression != _NO_COMPRESSION:
            continue  # heatshrink: not used for metadata by PrusaSlicer, and not worth a dependency
        yield kind, data


# ------------------------------------------------------------------ the slicer's filament estimate

_FILAMENT_KEYS = {"filament used [mm]": "filament_mm", "filament used [g]": "filament_g", "filament cost": "filament_cost"}
_FILAMENT_RE = re.compile(rb"^[ \t;]*(filament used \[mm\]|filament used \[g\]|filament cost)[ \t]*=([^\r\n]*)", re.MULTILINE)


def slicer_filament(file_obj, filename: str | None) -> dict:
    """
    {filament_mm, filament_g, filament_cost}: the slicer's estimate for the whole print (with several filaments, all
    of them added up); None where the file doesn't say. A file that isn't a G-code Farmhand understands answers all
    None; OSError when it can't be read at all. The file is left at its start.
    """
    out = dict.fromkeys(_FILAMENT_KEYS.values())
    try:
        if (filename or "").lower().endswith(".bgcode"):
            texts = [data for _, data in _bgcode_blocks(file_obj, {_PRINTER_METADATA, _PRINT_METADATA})]
        else:
            texts = [_tail(file_obj)]
    except (ValueError, struct.error, zlib.error):
        return out
    finally:
        file_obj.seek(0)
    for text in texts:
        for key, value in _FILAMENT_RE.findall(text):
            name = _FILAMENT_KEYS[key.decode()]
            if out[name] is None:
                out[name] = _total(value.decode("utf-8", "replace"))
    return out


def _total(value: str) -> float | None:
    """ "39324.56" or "120.5, 30.25" (one per filament) -> their sum; None if it isn't numbers """
    try:
        numbers = [float(v) for v in value.replace(";", ",").split(",") if v.strip()]
    except ValueError:
        return None
    total = sum(numbers)
    return round(total, 3) if numbers and math.isfinite(total) and total >= 0 else None



# ------------------------------------------------------------------ the filament's price, density and diameter

_SETTINGS_RE = re.compile(rb"^[ \t;]*(filament_cost|filament_density|filament_diameter)[ \t]*=([^\r\n]*)", re.MULTILINE)


def filament_settings(file_obj, filename: str | None) -> dict[str, str]:
    """
    {"filament_cost": "27.82", "filament_density": "1.27", "filament_diameter": "1.75"} as the slicer wrote them (one
    value per filament, comma separated), from a .bgcode's settings block or the end of a .gcode; a key is left out
    when the file doesn't say. The file is left at its start.
    """
    try:
        if (filename or "").lower().endswith(".bgcode"):
            texts = [data for _, data in _bgcode_blocks(file_obj, {_SLICER_METADATA})]
        else:
            texts = [_tail(file_obj)]
    except (OSError, ValueError, struct.error, zlib.error):
        return {}
    finally:
        file_obj.seek(0)
    out: dict[str, str] = {}
    for text in texts:
        for key, value in _SETTINGS_RE.findall(text):
            out.setdefault(key.decode(), value.decode("utf-8", "replace").strip())
    return out


def bgcode_settings_in(start: bytes) -> bool:
    """
    Whether this much of a .bgcode's start already holds its settings block (or shows it has none: its moves begin,
    or it isn't a .bgcode): so a file read from a printer can stop there, long before the moves.
    """
    if len(start) < 10:
        return False
    if start[:4] != b"GCDE":
        return True
    checksum_size = 4 if struct.unpack("<H", start[8:10])[0] == 1 else 0
    pos = 10
    while True:
        if pos + 8 > len(start):
            return False
        kind, compression, size = struct.unpack_from("<HHI", start, pos)
        if kind == _GCODE:
            return True
        head = 12 if compression != _NO_COMPRESSION else 8
        if pos + head > len(start):
            return False
        stored = struct.unpack_from("<I", start, pos + 8)[0] if compression != _NO_COMPRESSION else size
        end = pos + head + (6 if kind == _THUMBNAIL else 2) + stored + checksum_size
        if kind == _SLICER_METADATA:
            return end <= len(start)
        pos = end
