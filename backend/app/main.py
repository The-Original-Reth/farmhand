from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from . import background, change_hooks, storage
from .database import SessionLocal, create_schema, engine
from .notes import NotesConflict, conflict_response
from .routers import (
    bundles, config_settings, farm_cost, moonraker, plugin_api, plugins, printers, projects, prusalink, source_models,
    storage_settings,
)
from .services import storage_settings_service
from .services.moonraker import MoonrakerError
from .services.prusalink import PrusaLinkError
from .services.send_print import PrinterBusy

logger = logging.getLogger("farmhand.startup")

app = FastAPI(
    title="Farmhand",
    description=(
        "Catalogs and versions a 3D print farm's files (STL models, the 3MFs sliced from them, G-code, projects) and "
        "talks to its printers (Klipper/Moonraker, Prusa/PrusaLink): print history, power, maintenance, sending prints."
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

change_hooks.install(app)  # what a change made through the API writes to the NAS afterwards


app.include_router(printers.router)
app.include_router(projects.router)
app.include_router(source_models.router)
app.include_router(bundles.router)
app.include_router(storage_settings.router)
app.include_router(config_settings.router)
app.include_router(moonraker.router)
app.include_router(prusalink.router)
app.include_router(farm_cost.router)
app.include_router(plugins.router)
app.include_router(plugin_api.router)  # for plugins' containers only: see docs/plugins.md


@app.exception_handler(NotesConflict)
async def notes_conflict_handler(request: Request, exc: NotesConflict):
    # a notes save that lost to someone else's: 409 with the notes as they now stand (nothing was overwritten)
    return conflict_response(exc)


@app.exception_handler(MoonrakerError)
@app.exception_handler(PrusaLinkError)
async def printer_error_handler(request: Request, exc: MoonrakerError | PrusaLinkError):
    # the printer couldn't be reached or refused: a clear 502 saying which, not a generic 500
    return JSONResponse(status_code=502, content={"detail": str(exc), "kind": exc.kind})


@app.exception_handler(PrinterBusy)
async def printer_busy_handler(request: Request, exc: PrinterBusy):
    # a print sent to a printer that's printing (or otherwise not ready): 409, saying what it's doing
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(storage.StorageUnavailableError)
async def storage_unavailable_handler(request: Request, exc: storage.StorageUnavailableError):
    # e.g. a network share that isn't mounted right now: a clear 503, not a generic 500
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.on_event("startup")
def on_startup() -> None:
    # No Alembic: create_schema adds missing tables and indexes but never alters
    # existing columns (see database.create_schema).
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
            background.start_all()  # shares, printers, Farm cost, records... (app/background.py)
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
    background.stop_all()


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    from .config import settings

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
