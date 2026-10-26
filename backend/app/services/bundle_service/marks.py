"""What people add to a 3MF: the one version starred as the best (never the initial one), and the notes about it.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...errors import NotFound
from ... import notes as notes_helper
from ...models import Bundle, BundleNote, BundleStar, BundleVersion
from .queries import get_bundle


class StarNotAllowed(ValueError):
    """The version can't be starred (not part of this 3MF, or its initial version)."""


def set_starred_version(db: Session, bundle_id: int, version_id: int | None) -> Bundle:
    """
    Star one version of a 3MF (gold), or clear the star with None. Only one version per 3MF is starred: starring
    another moves the star there. Version 1, the initial upload, can't be starred (it always shows as silver).
    """
    bundle = get_bundle(db, bundle_id)
    if bundle is None:
        raise NotFound(f"No bundle with id {bundle_id}")
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


def set_notes(db: Session, bundle_id: int, notes: str, base_revision: int) -> Bundle:
    """Save the notes for a 3MF (the rules are in app/notes.py: conflict-safe, tidied, length-limited)."""
    bundle = get_bundle(db, bundle_id)
    if bundle is None:
        raise NotFound(f"No bundle with id {bundle_id}")
    return notes_helper.save(
        db, owner=bundle, note_cls=BundleNote, owner_key="bundle_id", base_revision=base_revision,
        notes=notes, reload=lambda: get_bundle(db, bundle_id),
    )
