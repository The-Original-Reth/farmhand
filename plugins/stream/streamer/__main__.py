"""Start the plugin: python -m streamer (what the Dockerfile runs)."""
from __future__ import annotations

import uvicorn

from . import config, migrate, store
from .app import app
from .live_stream import stream


@app.on_event("startup")
def _started() -> None:
    s = store.store()
    migrate.at_start(s)  # the first start: Farmhand's Stream page set-up brought over, when allowed
    stream.resume(s, store.session_factory)  # live before the restart: live again


@app.on_event("shutdown")
def _stopping() -> None:
    stream.stop(forget=False)  # (only the container stopping: it goes live again when it starts)


def main() -> None:
    settings = config.settings
    print(f"stream: listening on port {settings.port}; Farmhand is at {settings.farmhand_url or '(FARMHAND_URL not set)'}; "
          f"stream folder {settings.media_dir}; settings in {settings.data_dir}"
          + (f"; TRYING OUT: the stream goes to {settings.test_destination}, never to YouTube" if settings.test_destination else ""),
          flush=True)
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
