"""
The per-printer and per-model files Farmhand keeps next to its settings file on the network storage, so what lives
only in Farmhand's database (printers and everything about them, notes on models and 3MF files) survives a rebuild
and can be put back with Restore — the same way the model files themselves live on the NAS.

    <settings folder>/farmhand-config.json      appearance, preferences, storage, shares (config_store)
    <settings folder>/printers/<name>.json      one printer: settings, notes, 1500-hour service, print history,
                                                power meter readings
    <settings folder>/models/<name>.json        one model: its notes, and each of its 3MF files' notes and star

Like the settings file, these NEVER contain a secret: a printer's Moonraker API key is left out.

This module is the format and the file handling only. No database, so it's easy to test.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

RECORD_MARKER = "farmhand_record"  # the key that says "this is one of ours", and what kind
RECORD_VERSION = 1
PRINTERS_DIR = "printers"
MODELS_DIR = "models"
MAX_RECORD_BYTES = 50_000_000  # a printer with years of history is a few MB

_UNSAFE = re.compile(r"[^A-Za-z0-9 ._()+-]")


class RecordFileError(ValueError):
    """A record file exists but can't be used."""


def file_stem(name: str, taken: set[str]) -> str:
    """
    A file name for something called `name`: readable, safe on any NAS, and different from those already `taken`
    (case-insensitively, since Windows shares ignore case). "V2 BOG" -> "V2 BOG"; "a/b:c" -> "a_b_c".
    """
    stem = _UNSAFE.sub("_", name).strip(" .") or "unnamed"
    stem = stem[:120]
    candidate, n = stem, 2
    while candidate.lower() in taken:
        candidate = f"{stem} ({n})"
        n += 1
    taken.add(candidate.lower())
    return candidate


def _dumps(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def write_records(folder: str | os.PathLike, kind_dir: str, documents: dict[str, dict]) -> dict:
    """
    Make <folder>/<kind_dir> hold exactly these documents ({file stem: document}). Each file is written atomically,
    and only when its contents changed. Files of ours that no longer belong to anything are removed; anything
    else in the folder is left alone. Returns {"written": n, "removed": n}.
    """
    target_dir = Path(folder) / kind_dir
    target_dir.mkdir(exist_ok=True)
    written = removed = 0
    wanted = set()
    for stem, document in documents.items():
        target = target_dir / f"{stem}.json"
        wanted.add(target.name.lower())
        text = _dumps(document)
        try:
            if target.read_text(encoding="utf-8") == text:
                continue
        except (OSError, UnicodeDecodeError):
            pass
        part = target.with_name(target.name + ".part")
        try:
            part.write_text(text, encoding="utf-8")
            os.replace(part, target)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        written += 1
    for path in target_dir.glob("*.json"):
        if path.name.lower() in wanted:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # not ours to judge
        if isinstance(raw, dict) and raw.get(RECORD_MARKER) == kind_dir:
            path.unlink(missing_ok=True)
            removed += 1
    return {"written": written, "removed": removed}


def read_records(folder: str | os.PathLike, kind_dir: str) -> tuple[list[dict], list[str]]:
    """Every usable record of this kind in the folder, and a warning for each file that couldn't be used."""
    target_dir = Path(folder) / kind_dir
    if not target_dir.is_dir():
        return [], []
    records, warnings = [], []
    for path in sorted(target_dir.glob("*.json")):
        try:
            if path.stat().st_size > MAX_RECORD_BYTES:
                raise RecordFileError("it's far too large to be one of Farmhand's")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get(RECORD_MARKER) != kind_dir:
                raise RecordFileError("it isn't a Farmhand file")
            if not isinstance(raw.get("version"), int) or raw["version"] > RECORD_VERSION:
                raise RecordFileError("it was written by a newer Farmhand than this one")
            if not isinstance(raw.get("name"), str) or not raw["name"].strip():
                raise RecordFileError("it has no name in it")
        except RecordFileError as e:
            warnings.append(f"{kind_dir}/{path.name} was skipped: {e}.")
            continue
        except (OSError, ValueError) as e:
            warnings.append(f"{kind_dir}/{path.name} was skipped: it can't be read ({e}).")
            continue
        records.append(raw)
    return records, warnings


def header(kind_dir: str, name: str) -> dict:
    return {RECORD_MARKER: kind_dir, "version": RECORD_VERSION, "name": name}
