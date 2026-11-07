from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from . import storage
from .database import SessionLocal, create_schema, engine
from .mount_supervisor import supervisor
from .notes import NotesConflict, conflict_response
from .printer_poller import poller
from .farm_cost_recorder import recorder as farm_cost_recorder
from .routers import bundles, config_settings, farm_cost, moonraker, printers, projects, prusalink, source_models, storage_settings
from .services import (
    bundle_service, config_service, library_records, previews, project_records, project_scan, storage_settings_service,
    sub_printer_service,
)
from .services.moonraker import MoonrakerError
from .services.prusalink import PrusaLinkError

logger = logging.getLogger("farmhand.startup")

app = FastAPI(
    title="Farmhand",
    description=(
        "Cataloging and versioning system for a 3D print farm's 3MF files. Does not slice or send jobs to "
        "printers; it reads each printer's print history from Moonraker and shares maintenance reminders with it."
    ),
    version="0.1.0",
)

# Dev-friendly CORS: the frontend runs on its own port (3636), a different
# origin from the API (4545), so the browser needs explicit permission.
# Matching by regex (any host, port 3636) rather than a fixed "localhost"
# origin, since this is commonly accessed by its LAN IP or hostname (e.g.
# a Raspberry Pi reached from another machine) rather than literally
# "localhost". No cookies/auth are used, so allow_credentials stays off —
# tighten this to a real domain allowlist before this is exposed beyond
# a trusted local network.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*:3636$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def keep_settings_copy_current(request: Request, call_next):
    # A change to a printer, a model or a 3MF file (notes, stars, settings, a sync...) is copied to the settings
    # folder's printers/ and models/ files shortly after, in the background (config_service.request_mirror)
    response = await call_next(request)
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and response.status_code < 400:
        scope = _what_changed(request.url.path)
        if scope is not None:
            config_service.request_mirror(scope)
        # ...and a change to a project is written to its record in its own folder (project_records)
        parts = request.url.path.strip("/").split("/")
        one = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        if parts[0] == "projects":
            project_records.request_write(one)
        # ...and a model's or 3MF's to its record beside its files (library_records)
        if parts[0] == "source-models":
            library_records.request_write("model", one)
        if parts[0] == "bundles" and parts[-1] != "inspect":
            library_records.request_write("bundle", one)
    return response


def _what_changed(path: str) -> "config_service.MirrorScope | None":
    """Which files of the settings copy a successful change at this path touches (None: none of them)."""
    parts = path.strip("/").split("/")
    if parts[0] == "printers":
        if len(parts) > 2 and parts[1].isdigit():
            return config_service.MirrorScope(printers={int(parts[1])})  # its notes, a sync, its service...
        return config_service.EVERYTHING  # added, renamed, retired or deleted: file names and models' files follow
    if parts[0] in ("bundles", "source-models"):
        if parts[-1] == "inspect":
            return None  # only reads the 3MF
        if parts[-1] == "print":
            return config_service.MirrorScope(printers=True)  # a print sent: its printer's history may have it
        return config_service.MirrorScope(models=True)
    return None


app.include_router(printers.router)
app.include_router(projects.router)
app.include_router(source_models.router)
app.include_router(bundles.router)
app.include_router(storage_settings.router)
app.include_router(config_settings.router)
app.include_router(moonraker.router)
app.include_router(prusalink.router)
app.include_router(farm_cost.router)


@app.exception_handler(NotesConflict)
async def notes_conflict_handler(request: Request, exc: NotesConflict):
    # a notes save that lost to someone else's: 409 with the notes as they now stand (nothing was overwritten)
    return conflict_response(exc)


@app.exception_handler(MoonrakerError)
@app.exception_handler(PrusaLinkError)
async def printer_error_handler(request: Request, exc: MoonrakerError | PrusaLinkError):
    # the printer couldn't be reached or refused: a clear 502 saying which, not a generic 500
    return JSONResponse(status_code=502, content={"detail": str(exc), "kind": exc.kind})


@app.exception_handler(storage.StorageUnavailableError)
async def storage_unavailable_handler(request: Request, exc: storage.StorageUnavailableError):
    # e.g. a network share that isn't mounted right now: a clear 503, not a generic 500
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _keep_projects_folder_in() -> None:
    """
    Each project's record written to its folder once (a minute after starting, when the shares are mounted), then the
    project files folder scanned every few minutes: projects another Farmhand sharing it has (or project folders
    dropped in) come in on their own.
    """
    time.sleep(60)
    try:
        with SessionLocal() as db:
            library_records.write_all(db)
            project_records.write_all(db)
    except Exception:  # noqa: BLE001 - this must never stop
        logger.exception("Writing the records failed")
    while True:
        try:
            with SessionLocal() as db:
                library = library_records.import_library(db)  # models and 3MFs first: projects name them
                result = project_scan.import_projects_folder(db, auto=True)
            for name in library["models"] + library["threemfs"]:
                logger.info("Brought in %s from the shared folders", name)
            for p in result["imported"]:
                logger.info("Brought in the project %s from the project files folder", p["name"])
        except storage.StorageUnavailableError:
            pass  # the folder is away: next time
        except Exception:  # noqa: BLE001 - this must never stop; it tries again in a few minutes
            logger.exception("Scanning the project files folder failed")
        time.sleep(300)


def _keep_previews_beside_models() -> None:
    """
    Previews are kept only next to their files. Copies the app kept itself (from before) are moved out to their files:
    a minute after starting (once the saved network shares are mounted), then every hour for shares that come back
    later.
    """
    wait = 60
    while True:
        time.sleep(wait)
        wait = 3600
        try:
            with SessionLocal() as db:
                moved = previews.move_app_copies_out(db)
            if moved:
                logger.info("Moved %d preview(s) out of the app to their files", moved)
        except Exception:  # noqa: BLE001 - this must never stop; it tries again in an hour
            logger.exception("Moving previews out to their files failed")


@app.on_event("startup")
def on_startup() -> None:
    # Simple create_all for now, appropriate for this stage. Move to real
    # Alembic migrations before this touches a production database with
    # data worth preserving across schema changes.
    import app.models  # noqa: F401  (ensures all models are registered on Base)

    # Retry with backoff instead of crashing: in docker-compose, the db
    # container's healthcheck passing doesn't always mean Docker's embedded
    # DNS has the 'db' hostname resolvable yet for every other container on
    # the first attempt (seen in practice, e.g. on some Raspberry Pi / UFW
    # setups where inter-container DNS can be flaky at startup). Fail loud
    # after real retries, not after one race-condition-prone attempt.
    max_attempts = 10
    delay_seconds = 3
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            create_schema(engine)
            if attempt > 1:
                logger.info("Connected to the database on attempt %d/%d", attempt, max_attempts)
            # Pick up the storage locations chosen in the UI
            with SessionLocal() as db:
                storage_settings_service.apply_saved_locations(db)
            # Re-mount saved network shares (and keep them mounted). In a thread: a slow
            # or unreachable NAS must never delay the API coming up.
            supervisor.start()
            # Sync every printer's history and power meter now and then, so energy figures build up on their own
            poller.start()
            # Once a month is over, its Farm cost table is saved as a record in the "farm cost" folder
            farm_cost_recorder.start()
            # Changes to printers and models get copied to the settings folder in the background, and once now
            config_service.enable_background_mirror()
            config_service.request_mirror()
            threading.Thread(target=_keep_previews_beside_models, name="previews-beside", daemon=True).start()
            # Projects written to their folders, and ones in the project files folder that aren't here brought in
            project_records.enable_background_writes()
            library_records.enable_background_writes()
            threading.Thread(target=_keep_projects_folder_in, name="projects-folder", daemon=True).start()
            # 3MF versions from before printer profiles: linked to the printer preset each was sliced with, once
            threading.Thread(
                target=sub_printer_service.run_link_missing, args=(SessionLocal,), name="sub-printers", daemon=True
            ).start()
            # 3MFs from before auto-starring: each one's newest version starred, once
            threading.Thread(
                target=bundle_service.run_star_existing, args=(SessionLocal,), name="stars", daemon=True
            ).start()
            return
        except OperationalError as e:
            last_error = e
            logger.warning(
                "Database not reachable yet (attempt %d/%d): %s — retrying in %ds",
                attempt, max_attempts, str(e).splitlines()[0], delay_seconds,
            )
            time.sleep(delay_seconds)
    raise RuntimeError(
        f"Could not reach the database after {max_attempts} attempts. "
        f"Last error: {last_error}"
    )


@app.on_event("shutdown")
def on_shutdown() -> None:
    supervisor.stop()
    poller.stop()


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    from .config import settings

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
