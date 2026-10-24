from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from . import storage
from .database import Base, SessionLocal, engine
from .mount_supervisor import supervisor
from .routers import bundles, config_settings, printers, source_models, storage_settings
from .services import storage_settings_service

logger = logging.getLogger("farmhand.startup")

app = FastAPI(
    title="Farmhand",
    description=(
        "Read-only cataloging and versioning system for a 3D print farm's "
        "3MF files. Does not slice, does not talk to printers."
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

app.include_router(printers.router)
app.include_router(source_models.router)
app.include_router(bundles.router)
app.include_router(storage_settings.router)
app.include_router(config_settings.router)


@app.exception_handler(storage.StorageUnavailableError)
async def storage_unavailable_handler(request: Request, exc: storage.StorageUnavailableError):
    # e.g. a network share that isn't mounted right now: a clear 503, not a generic 500
    return JSONResponse(status_code=503, content={"detail": str(exc)})


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


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    from .config import settings

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
