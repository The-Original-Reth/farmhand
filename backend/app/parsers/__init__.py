from __future__ import annotations

from . import orcaslicer, prusaslicer
from .prusaslicer import ParsedBundle
from .threemf import RawThreeMF, detect_slicer_family, read_3mf

__all__ = ["ParsedBundle", "RawThreeMF", "parse_3mf"]

_PARSERS = {
    "prusaslicer": prusaslicer.parse,
    "orcaslicer": orcaslicer.parse,
    "bambustudio": lambda raw: orcaslicer.parse(raw, "bambustudio"),
}


def parse_3mf(path: str) -> ParsedBundle:
    """
    Read a .3mf file from disk and parse it with whichever slicer-family
    parser applies. Raises ValueError if the file has no recognizable
    slicer config at all (or one that can't be read).
    """
    raw = read_3mf(path)
    if raw.config_text is None:
        raise ValueError(
            f"No slicer config found in {path!r} (checked: "
            f"{', '.join(prusaslicer_and_friends_paths())}) — is this a "
            "valid PrusaSlicer, OrcaSlicer or Bambu Studio .3mf?"
        )
    family = detect_slicer_family(raw)
    parser = _PARSERS.get(family)
    if parser is None:
        raise ValueError(f"Unrecognized slicer family: {family!r}")
    return parser(raw)


def prusaslicer_and_friends_paths() -> list[str]:
    from .threemf import CONFIG_CANDIDATES

    return CONFIG_CANDIDATES
