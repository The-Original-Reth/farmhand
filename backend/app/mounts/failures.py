"""The last mount failure of each share, kept in memory so the Storage page can say why a share isn't connected."""
from __future__ import annotations


# ------------------------------------------------------------------ remembering the last failure per share
# (in memory: it's about the current state of the connection, not something worth saving)

_errors: dict[int, tuple[str, str]] = {}


def set_error(share_id: int, kind: str, message: str) -> None:
    _errors[share_id] = (kind, message)


def clear_error(share_id: int) -> None:
    _errors.pop(share_id, None)


def get_error(share_id: int) -> tuple[str, str] | None:
    return _errors.get(share_id)
