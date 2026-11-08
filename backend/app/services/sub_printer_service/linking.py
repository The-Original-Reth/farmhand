"""Each 3MF version linked to the printer profile it was sliced with, adding a profile it names that isn't known yet."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Bundle, BundleVersion, BundleVersionSubPrinter, Printer, SubPrinter
from .core import MAX_NAME, _clean, _named, _new, _remember, known_as, logger


def link(
    db: Session, version: BundleVersion, printer: Printer, preset_name: str | None,
    *, sub_printer_id: int | None = None, new_name: str | None = None,
) -> None:
    """
    Note which printer profile `version` goes to. Picked on upload: `sub_printer_id` (one of the printer's), or
    `new_name` (a new one, or the printer's one by that name). Else the one its preset goes to (known_as), added to
    `printer` if it isn't known yet. A preset put with a printer profile by another name is remembered for next time.
    ValueError for a printer profile that isn't the printer's. Doesn't commit: the caller does, with the version.
    """
    sub = None
    preset = (preset_name or "").strip()[:MAX_NAME]
    if sub_printer_id is not None:
        sub = db.get(SubPrinter, sub_printer_id)
        if sub is None or sub.printer_id != printer.id:
            raise ValueError(f"That printer profile isn't one of {printer.name}'s")
    elif new_name and new_name.strip():
        name = _clean(new_name)
        sub = _named(db, printer.id, name) or _new(printer, name)
    elif preset:
        sub = known_as(db, printer.id, preset) or _new(printer, preset)
    if sub is not None and preset:
        _remember(db, sub, preset)
    version.sub_printer_link = BundleVersionSubPrinter(bundle_version_id=version.id, sub_printer=sub)


def link_missing(db: Session) -> int:
    """
    3MF versions uploaded before printer profiles existed: read the preset each was sliced with from its kept settings,
    and link it. Each version is only looked at once. Returns how many were linked to a printer profile.
    """
    linked = 0
    rows = db.execute(
        select(BundleVersion, Bundle.printer_id)
        .join(Bundle, Bundle.id == BundleVersion.bundle_id)
        .outerjoin(BundleVersionSubPrinter, BundleVersionSubPrinter.bundle_version_id == BundleVersion.id)
        .where(BundleVersionSubPrinter.bundle_version_id.is_(None))
        .order_by(BundleVersion.id)
    ).all()
    for version, printer_id in rows:
        name = (version.settings or {}).get("printer_settings_id")
        link(db, version, db.get(Printer, printer_id), name if isinstance(name, str) else None)
        db.flush()  # a name met twice is found the second time
        linked += version.sub_printer_id is not None
    db.commit()
    return linked


def run_link_missing(session_factory) -> None:
    """At startup: link the 3MF versions from before printer profiles. Never stops the API from coming up."""
    try:
        with session_factory() as db:
            linked = link_missing(db)
        if linked:
            logger.info("Linked %d 3MF version(s) to their printer profiles", linked)
    except Exception:  # noqa: BLE001 - a version that can't be read stays unlinked; the rest of Farmhand carries on
        logger.exception("Linking 3MF versions to their printer profiles failed")
