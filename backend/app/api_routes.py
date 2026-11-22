"""
Every route of the API, as ["METHOD", "/path"] pairs, written to frontend/mock/api-routes.json by
`python -m app.api_routes`. The mock backend is checked against that file (`npm run check:mock` in frontend/), so a
route added here and not to the mock is caught; tests/test_api_routes.py fails while the file is out of date.

Only the documented routes (the OpenAPI schema): the two left out of it (farmhand-plugin.js and a plugin's page) are
passed on to plugins, which the mock answers in its own way.
"""
from __future__ import annotations

import json
from pathlib import Path

METHODS = ("get", "post", "put", "patch", "delete")
FILE = Path(__file__).resolve().parents[2] / "frontend" / "mock" / "api-routes.json"


def routes() -> list[list[str]]:
    from .main import app

    paths = app.openapi()["paths"]
    return sorted([m.upper(), path] for path, ops in paths.items() for m in ops if m in METHODS)


def as_text() -> str:
    """The file's contents: one route per line, so a change shows as a one-line diff."""
    return "[\n" + ",\n".join(f"  {json.dumps(r)}" for r in routes()) + "\n]\n"


if __name__ == "__main__":
    FILE.write_text(as_text(), encoding="utf-8", newline="\n")
    print(f"Wrote {len(routes())} routes to {FILE}")
