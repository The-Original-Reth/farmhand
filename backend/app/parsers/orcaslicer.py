"""
Parser for OrcaSlicer 3MF files — STUB.

Per spec, OrcaSlicer needs its own parser (separate from the shared
PrusaSlicer/BOSS one, since Orca's config uses different key names and
structure). Not implemented yet: we don't have a real OrcaSlicer-exported
.3mf to build and test against. Wire this up the same way prusaslicer.py
was — real sample file first, then parser — rather than guessing at the
format.
"""
from __future__ import annotations

from .prusaslicer import ParsedBundle
from .threemf import RawThreeMF


def parse(raw: RawThreeMF) -> ParsedBundle:
    raise NotImplementedError(
        "OrcaSlicer parsing isn't implemented yet — no real sample file has "
        "been parsed against it. Get a real OrcaSlicer-exported .3mf and "
        "extend this module the way prusaslicer.py was built, rather than "
        "guessing at the config format."
    )
