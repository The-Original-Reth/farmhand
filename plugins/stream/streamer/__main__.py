"""Start the plugin: python -m streamer (what the Dockerfile runs)."""
from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn

from . import config, migrate, store
from .app import app
from .live_stream import stream


@asynccontextmanager
async def _running(_app):
    """While the plugin runs (set here, not in app.py, so tests using the app never go live by themselves)."""
    s = store.store()
    migrate.at_start(s)  # the first start: Farmhand's Stream page set-up brought over, when allowed
    stream.resume(s, store.session_factory)  # live before the restart: live again
    yield
    # (only the container stopping: it goes live again when it starts, on the same YouTube broadcast, so that's left live)
    stream.stop(forget=False, end_broadcast=False)


app.router.lifespan_context = _running


def main() -> None:
    settings = config.settings
    print(f"stream: listening on port {settings.port}; Farmhand is at {settings.farmhand_url or '(FARMHAND_URL not set)'}; "
          f"stream folder {settings.media_dir}; settings in {settings.data_dir}"
          + (f"; TRYING OUT: the stream goes to {settings.test_destination}, never to YouTube" if settings.test_destination else ""),
          flush=True)
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
