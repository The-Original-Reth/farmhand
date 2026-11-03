"""What people add to a 3MF: the one version starred as the best (never the initial one), and the notes about it.
When none is starred, the newest version is starred for them as versions come and go (star_newest_if_none).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import notes as notes_helper
from .. import app_settings
from ...models import Bundle, BundleNote, BundleStar, BundleVersion
from .queries import get_bundle, require_bundle

logger = logging.getLogger("farmhand.bundles")


class StarNotAllowed(ValueError):
    """The version can't be starred (not part of this 3MF, or its initial version)."""


def set_starred_version(db: Session, bundle_id: int, version_id: int | None) -> Bundle:
    """
    Star one version of a 3MF (gold), or clear the star with None. Only one version per 3MF is starred: starring
    another moves the star there. Version 1, the initial upload, can't be starred (it always shows as silver).
    """
    bundle = require_bundle(db, bundle_id)
    if version_id is None:
        bundle.star_row = None  # delete-orphan removes the row
    else:
        version = db.get(BundleVersion, version_id)
        if version is None or version.bundle_id != bundle.id:
            raise StarNotAllowed(f"Version {version_id} isn't a version of this 3MF")
        if version.version == 1:
            raise StarNotAllowed("The initial version can't be starred")
        if bundle.star_row is None:
            bundle.star_row = BundleStar(bundle_id=bundle.id, version_id=version.id)
        else:
            bundle.star_row.version_id = version.id
    db.commit()
    db.refresh(bundle)
    return bundle


def star_newest_if_none(bundle: Bundle, versions: list[BundleVersion]) -> bool:
    """
    When none of a 3MF's versions is starred, star the newest of `versions` (the ones it has now). Never version 1, the
    initial upload, so a 3MF with only that one stays unstarred. Un-starring by hand stays as it is until a version is
    next added or the starred one deleted. Doesn't commit. True if it starred one.
    """
    if bundle.star_row is not None:
        return False
    newest = max(versions, key=lambda v: v.version, default=None)
    if newest is None or newest.version == 1:
        return False
    bundle.star_row = BundleStar(bundle_id=bundle.id, version_id=newest.id)
    return True


STARRED_EXISTING_KEY = "bundles.newest_starred"  # set once the 3MFs from before auto-starring have been starred


def star_existing(db: Session) -> int:
    """
    Once: every 3MF that has no starred version gets its newest one starred, as one uploaded now would. Later starts
    leave them alone, so a star cleared by hand stays cleared. Returns how many were starred.
    """
    if app_settings.get(db, STARRED_EXISTING_KEY):
        return 0
    starred = sum(star_newest_if_none(b, list(b.versions)) for b in db.scalars(select(Bundle)))
    app_settings.put(db, STARRED_EXISTING_KEY, "1")
    db.commit()
    return starred


def run_star_existing(session_factory) -> None:
    """At startup, in the background: star_existing. Never stops the API from coming up."""
    try:
        with session_factory() as db:
            starred = star_existing(db)
        if starred:
            logger.info("Starred the newest version of %d 3MF file(s)", starred)
    except Exception:  # noqa: BLE001 - nothing here is worth stopping Farmhand for
        logger.exception("Starring the newest 3MF versions failed")


def set_notes(db: Session, bundle_id: int, notes: str, base_revision: int) -> Bundle:
    """Save the notes for a 3MF (the rules are in app/notes.py: conflict-safe, tidied, length-limited)."""
    bundle = require_bundle(db, bundle_id)
    return notes_helper.save(
        db, owner=bundle, note_cls=BundleNote, owner_key="bundle_id", base_revision=base_revision,
        notes=notes, reload=lambda: get_bundle(db, bundle_id),
    )
