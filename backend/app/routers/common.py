"""
What several routers answer the same way: a printer, model, 3MF or version that isn't there, a delete that wasn't confirmed, a stored file
that can't be read right now, a preview image, a picture or track of Stream control's stream, and how a printer's last sync went.
"""
from __future__ import annotations

import os

from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from .. import storage
from ..models import Bundle, BundleVersion, Printer, SourceModel, SourceModelVersion
from ..services import bundle_service, printer_service, source_model_service
from ..timeutil import utc_iso

CONFIRM_DELETE = "Deleting is permanent — pass confirm=true to proceed"

# An SVG can carry scripts: opened on its own it would run them as this page. It's sent as a picture that can't.
SVG_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox",
               "X-Content-Type-Options": "nosniff"}


def stream_picture_response(path) -> Response:
    """A picture of Stream control's stream folder (for its page, and the stream plugins through the plugin API)."""
    from ..services.stream_control import media

    kind = media.PICTURE_TYPES[path.suffix.lower()]
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "no-cache", **(SVG_HEADERS if kind == "image/svg+xml" else {})})


def stream_track_response(where) -> Response:
    """A track of the stream's music, as stream_control.music_sources.find found it: Stream control's own file, or a
    stream plugin's passed on as it comes (NotFound when that plugin hasn't got it)."""
    from ..services.stream_control import media, music_sources

    if isinstance(where, tuple):
        address, path = where
        return StreamingResponse(music_sources.passed_on(address, path), media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})
    return FileResponse(where, media_type=media.TRACK_TYPES[where.suffix.lower()], headers={"Cache-Control": "no-cache"})


def _found(thing, detail: str):
    if thing is None:
        raise HTTPException(status_code=404, detail=detail)
    return thing


def require_printer(db: Session, printer_id: int) -> Printer:
    return _found(printer_service.get_printer(db, printer_id), "Printer not found")


def require_source_model(db: Session, source_model_id: int) -> SourceModel:
    return _found(source_model_service.get_source_model(db, source_model_id), "Source model not found")


def require_source_model_version(db: Session, source_model_id: int, version: int) -> SourceModelVersion:
    v = source_model_service.get_source_model_version(db, source_model_id, version)
    return _found(v, "Source model version not found")


def require_bundle(db: Session, bundle_id: int) -> Bundle:
    return _found(bundle_service.get_bundle(db, bundle_id), "Bundle not found")


def require_bundle_version(db: Session, version_id: int) -> BundleVersion:
    return _found(db.get(BundleVersion, version_id), "Bundle version not found")


def require_confirm(confirm: bool, detail: str = CONFIRM_DELETE) -> None:
    """Deleting is permanent, so each delete has to say confirm=true."""
    if not confirm:
        raise HTTPException(status_code=409, detail=detail)


def require_readable(path: str) -> None:
    """A stored file that's recorded but can't be read now: most likely on a network share that isn't mounted."""
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="That file isn't available right now. If it's stored on a network share, check that "
            "the share is mounted and reachable.",
        )


def preview_response(thumbnail_path: str | None, file_path: str | None, request: Request) -> FileResponse:
    """
    A version's preview: the one kept next to its file (thumbnail_path; a pruned 3MF's stays where the 3MF was), else
    one found next to the file. Nothing is kept in the app, so a preview on a share that's offline is a 404 until it's
    back. thumbnail_path and file_path are both None for a version that doesn't exist.
    """
    path = thumbnail_path if thumbnail_path and os.path.isfile(thumbnail_path) else storage.preview_beside(file_path)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="No thumbnail for this version")
    return FileResponse(path, media_type="image/png", headers=storage.preview_cache_headers(request.query_params))


def sync_state(printer: Printer) -> dict:
    """When Farmhand last heard from the printer, what went wrong if that failed, and its lifetime totals."""
    conn = printer.connection_row
    return {
        "last_sync_at": utc_iso(conn.last_sync_at) if conn else None,
        "last_sync_error": conn.last_sync_error if conn else None,
        "totals": conn.totals if conn else None,
    }
