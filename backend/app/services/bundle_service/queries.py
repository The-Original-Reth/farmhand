"""Looking up 3MF files (bundles): one, every one, or those on a printer or sliced from a model.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Bundle, BundleSourceModel


def get_bundle(db: Session, bundle_id: int) -> Bundle | None:
    return db.get(Bundle, bundle_id)


def list_all_bundles(db: Session) -> list[Bundle]:
    return list(db.scalars(select(Bundle)))


def list_bundles_for_printer(db: Session, printer_id: int) -> list[Bundle]:
    return list(db.scalars(select(Bundle).where(Bundle.printer_id == printer_id)))


def list_bundles_for_source_model(db: Session, source_model_id: int) -> list[Bundle]:
    return list(
        db.scalars(
            select(Bundle)
            .join(BundleSourceModel)
            .where(BundleSourceModel.source_model_id == source_model_id)
        )
    )
