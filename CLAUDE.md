# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Farmhand catalogs and versions a 3D print farm's files (STL models, the 3MFs sliced from them, G-code) and talks
to the printers (Klipper/Moonraker, Prusa/PrusaLink). Backend: FastAPI + SQLAlchemy + PostgreSQL in `backend/`.
Frontend: React 18 + Vite (plain JSX, no TypeScript, no state library) in `frontend/`. User-facing docs live in
`README.md` and `backend/README.md` (the API table there is the endpoint reference); keep them current when
behaviour changes, since past commits do.

## Commands

```bash
docker compose up --build                 # everything: web :3636, API :4545 (/docs), Postgres :2727
docker compose exec api python -m app.seed  # load sample farm (needs files in backend/seed_data/)

cd backend && python -m pytest -q         # backend tests (in-memory SQLite, no Postgres needed)
cd backend && python -m pytest tests/test_moonraker.py::test_name -q   # single test
cd backend && uvicorn app.main:app --reload --port 4545                # API without Docker

cd frontend && npm run mock               # real UI on a fake in-memory backend, :3637, no Docker/API
cd frontend && VITE_API_BASE=http://localhost:4545 npm run dev   # UI against a local API
cd frontend && npm run build              # the only frontend "test"; there is no linter or unit test suite
cd frontend && npm run check:themes       # WCAG AA contrast check of every palette in src/palettes.js
```

Some backend tests are POSIX-only (`posix_only` marker in `tests/conftest.py`) and parser tests skip when the
real sample 3MFs aren't present.

## Architecture

**Data model** (`backend/app/models/`): Printer → SourceModel (STL/OBJ/STEP, versioned) → Bundle (a 3MF's
identity, locked to one printer) → BundleVersion. Bundle↔SourceModel is many-to-many (mixed plates). Only the
newest `FARMHAND_FULL_FILE_VERSION_WINDOW` (5) versions keep their files; "monument" versions are exempt.
Notes live in separate `*_note` tables with optimistic revisions (`app/notes.py`, 409 on conflict).

**Schema changes**: no Alembic. `database.create_schema()` runs `create_all` plus missing indexes at startup, so
it can add tables and indexes but never alters existing columns. New data usually goes in a new table for that
reason.

**Layering**: routers are thin; rules live in `app/services/`. Services raise `NotFound` or `ValueError`, and
routers wrap calls in `errors.answer_errors()` to turn them into 404/422 (or a route-specific code like 409).
Printer integrations are packages: `services/moonraker/` and `services/prusalink/`, with errors mapped to HTTP
in `main.py`. `printer_poller.py` and `mount_supervisor.py` are background threads started from `main.py`.

**Storage** (`app/storage.py`): STL and 3MF roots are chosen independently (Storage page, `app_settings` table)
and can sit on NAS shares that Farmhand mounts itself (`mounts.py`, needs `SYS_ADMIN` in Docker). The DB stores
absolute paths. Chosen roots must contain a `.farmhand-storage` marker or writes get 503 (that's how an
unmounted share is detected). Writes go to a temp name and are then renamed; deletes only remove recorded files,
never a recursive delete.

**Settings mirror**: a middleware in `main.py` calls `config_service.request_mirror()` after every successful
mutating request, which writes `farmhand-config.json` plus per-printer/per-model JSON files to a chosen folder.
`_what_changed()` maps URL paths to what gets rewritten, so a new mutating route under an unexpected prefix
needs an entry there. Passwords are never written to the mirror.

**Frontend**: `src/api.js` is the single HTTP client. It also normalizes API shapes into the shapes the UI
components use. The API host comes from the browser's own hostname at runtime (port 4545), and
`VITE_API_BASE` overrides it. `src/` has one folder per area (models, bundles, printers, power, storage,
monitor, notes, compare). Colours come from `palettes.js`/`theme.js`; don't hard-code colours, or the
contrast check stops covering them.

**Mock backend** (`frontend/mock/server.js` + `data.js`): a Vite plugin serving `/mock-api` in exactly the real
API's shapes. It is never built into the image (`.dockerignore`). **A new or changed endpoint must be mirrored
there**, and Moonraker/PrusaLink behaviour in the backend test stand-ins (`tests/fake_moonraker.py`,
`tests/fake_prusalink.py`). A typical feature commit touches router → service → test → `api.js` → mock → UI.

`app/mounts.py` `parse_location` and `frontend/src/location.js` must stay in agreement (the frontend copy
only drives the live preview).

## Conventions

- Commit subjects use the form `Area: plain-language outcome` (e.g. `Monitor: every printer's camera in one grid`).
- UI text and error messages are plain language aimed at a print-farm operator. Backend messages are shown
  verbatim in the UI, and printer errors are passed through as the printer's own answer, translated.
- Deletes require `?confirm=true` on the API. DB rows go first, then files.
