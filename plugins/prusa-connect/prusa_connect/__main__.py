"""Start the plugin: python -m prusa_connect (what the Dockerfile runs)."""
from __future__ import annotations

import signal
import sys

from .config import Config, Settings
from .connect import PrusaConnect
from .farmhand import Farmhand
from .reporter import Reporter
from .server import make_server


def main() -> None:
    config = Config.from_env()
    settings = Settings(config.data_dir, default_address=config.connect_url)
    reporter = Reporter(Farmhand(config.farmhand_url, config.farmhand_token), PrusaConnect(settings), settings)
    server = make_server(config.port, reporter, settings)

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # docker stop: stop cleanly

    print(
        f"prusa-connect: listening on port {config.port}; Farmhand is at {config.farmhand_url or '(FARMHAND_URL not set)'}; "
        f"Prusa Connect is at {settings.address or '(not set yet: choose it on the plugin page)'}",
        flush=True,
    )
    reporter.start()
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        reporter.stop()
        server.server_close()


if __name__ == "__main__":
    main()
