from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from . import storage
from .database import Base, SessionLocal, engine
from .mount_supervisor import supervisor
from .notes import NotesConflict, conflict_response
from .printer_poller import poller
from .routers import bundles, config_settings, moonraker, printers, prusalink, source_models, storage_settings
from .services import config_service, previews, storage_settings_service
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
# origin from the API (5546), so the browser needs explicit permission.
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
    if (
        request.method in ("POST", "PUT", "PATCH", "DELETE")
        and response.status_code < 400
        and request.url.path.startswith(("/printers", "/bundles", "/source-models"))
    ):
        config_service.request_mirror()
    return response


app.include_router(printers.router)
app.include_router(source_models.router)
app.include_router(bundles.router)
app.include_router(storage_settings.router)
app.include_router(config_settings.router)
app.include_router(moonraker.router)
app.include_router(prusalink.router)


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


def _keep_previews_beside_models() -> None:
    """
    Models and 3MF files from before previews were kept next to their files get a copy there: a minute after starting
    (once the saved network shares are mounted), then every hour for shares that come back later. Only missing ones
    are written.
    """
    wait = 60
    while True:
        time.sleep(wait)
        wait = 3600
        try:
            with SessionLocal() as db:
                saved = previews.save_missing_beside(db)
            if saved:
                logger.info("Saved %d preview(s) next to their files", saved)
        except Exception:  # noqa: BLE001 - this must never stop; it tries again in an hour
            logger.exception("Saving previews next to their files failed")


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
            Base.metadata.create_all(bind=engine)
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
            # Changes to printers and models get copied to the settings folder in the background, and once now
            config_service.enable_background_mirror()
            config_service.request_mirror()
            threading.Thread(target=_keep_previews_beside_models, name="previews-beside", daemon=True).start()
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
