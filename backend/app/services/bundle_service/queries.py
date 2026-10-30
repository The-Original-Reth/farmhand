"""Looking up 3MF files (bundles): one, every one, or those on a printer or sliced from a model.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...errors import NotFound
from ...models import Bundle, BundleSourceModel, BundleVersion, BundleVersionSubPrinter, SourceModel

# Everything a list of bundles shows (BundleOut), loaded a batch at a time rather than a few queries per bundle
LIST_LOAD = (
    selectinload(Bundle.versions)
    .selectinload(BundleVersion.sub_printer_link)
    .selectinload(BundleVersionSubPrinter.sub_printer),
    selectinload(Bundle.note_row),
    selectinload(Bundle.star_row),
    selectinload(Bundle.source_model_links).selectinload(BundleSourceModel.source_model).options(
        selectinload(SourceModel.versions), selectinload(SourceModel.note_row),
    ),
)


def get_bundle(db: Session, bundle_id: int) -> Bundle | None:
    return db.get(Bundle, bundle_id)


def require_bundle(db: Session, bundle_id: int) -> Bundle:
    """The bundle, or NotFound."""
    bundle = get_bundle(db, bundle_id)
    if bundle is None:
        raise NotFound(f"No bundle with id {bundle_id}")
    return bundle


def require_version(db: Session, version_id: int) -> BundleVersion:
    """The bundle version, or NotFound."""
    version = db.get(BundleVersion, version_id)
    if version is None:
        raise NotFound(f"No bundle version with id {version_id}")
    return version


def list_all_bundles(db: Session) -> list[Bundle]:
    return list(db.scalars(select(Bundle).options(*LIST_LOAD)))


def list_bundles_for_printer(db: Session, printer_id: int) -> list[Bundle]:
    return list(db.scalars(select(Bundle).where(Bundle.printer_id == printer_id).options(*LIST_LOAD)))


def list_bundles_for_source_model(db: Session, source_model_id: int) -> list[Bundle]:
    return list(
        db.scalars(
            select(Bundle)
            .join(BundleSourceModel)
            .where(BundleSourceModel.source_model_id == source_model_id)
            .options(*LIST_LOAD)
        )
    )
