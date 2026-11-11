"""Start the plugin: python -m hello (what the Dockerfile runs)."""
from __future__ import annotations

import signal
import sys

from .config import Config, Settings
from .farmhand import Farmhand
from .server import make_server
from .watcher import Watcher


def main() -> None:
    config = Config.from_env()
    settings = Settings(config.data_dir)
    watcher = Watcher(Farmhand(config.farmhand_url, config.farmhand_token), settings)
    server = make_server(config.port, watcher, settings)

    # docker stop sends SIGTERM: stop cleanly rather than being killed 10 s later
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    print(f"hello: listening on port {config.port}; Farmhand is at {config.farmhand_url or '(FARMHAND_URL not set)'}", flush=True)
    watcher.start()
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        watcher.stop()
        server.server_close()


if __name__ == "__main__":
    main()
