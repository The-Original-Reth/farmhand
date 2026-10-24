# Farmhand backend

Read-only cataloging and versioning system for a 3D print farm's 3MF files.
Stores, analyzes, and catalogs — does not slice, does not talk to printers.

This is the real backend behind the React mockup: FastAPI + SQLAlchemy +
PostgreSQL, with a genuine PrusaSlicer 3MF parser (tested against real
files from the farm, not synthetic ones).

## What's implemented

- **Data model**: Printer (trunk) → SourceModel (branch, with its own
  version history) → Bundle (a 3MF's persistent identity, locked to one
  printer) → BundleVersion (the versioned leaf). Bundle↔SourceModel is
  many-to-many — a single 3MF can be a mixed plate sliced from more than
  one source model, which real uploaded files proved is a real case the
  original 1:1 spec assumption didn't cover.
- **gcode is optional on upload**, not required alongside the 3MF — this
  relaxes the original spec's "3MF and gcode files must be uploaded
  together" rule. A bundle version can exist with just its 3MF; the gcode
  can be added later (not yet wired into the UI as a separate action, but
  the API already supports it via the same "Update" endpoint).
- **Real PrusaSlicer/BOSS parser** (`app/parsers/prusaslicer.py`): unzips a
  `.3mf`, reads `Metadata/Slic3r_PE.config`, extracts every setting
  (~458 keys on the real farm files), the embedded thumbnail, and the
  printer profile it was sliced for. Verified against all three real
  sample files from the mockup phase.
- **OrcaSlicer parser**: stubbed, not implemented — there's no real Orca-
  exported `.3mf` to build and test against yet. Don't guess at the
  format; get a sample file first, same as PrusaSlicer was done.
- **Versioning engine** (`app/services/bundle_service.py`): the rolling
  5-version full-file window, monument exemption (with required note to
  monument, required confirmation to un-monument), and the locked-printer
  rule (a bundle's printer can't change after creation; uploading an
  "Update" whose embedded profile doesn't match is rejected).
- **Upload flow** matching the UI decisions made in the mockup: creating a
  bundle can either take an explicit `printer_id`, or omit it entirely and
  have the printer read from the 3MF's own embedded profile (must already
  be registered under that exact name).

## What's NOT implemented yet

- OrcaSlicer parsing (stub only — see above)
- Alembic migrations — currently uses `Base.metadata.create_all()` on
  startup, fine for early development, not for a production DB with data
  worth preserving across schema changes
- Auth/permissions (none — internal tool assumption carried over from the
  mockup)
- STEP viewer / three.js rendering pipeline (deferred per spec, revisit
  once this core is further along)
- Cloud file storage (currently local disk under `storage/`, behind a
  small interface in `app/storage.py` so it can be swapped later)

## Setup — Docker Compose (recommended)

```bash
docker compose up --build
```

That's it — this starts Postgres and the API together, with the API on
**http://localhost:5546**. Interactive API docs (Swagger UI) are at
http://localhost:5546/docs. Data persists in named Docker volumes
(`db_data` for Postgres, `storage_data` for uploaded files) across
restarts; `docker compose down -v` wipes both if you want a clean slate.

Run the test suite inside the running container:

```bash
docker compose exec api pytest
```

Load the real farm data (2 printers, 3 STL source models with auto-generated
thumbnails, 3 real 3MF bundles including the mixed-plate Frog one) so the
frontend has something real to show:

```bash
docker compose exec api python -m app.seed
```

Safe to re-run — it skips anything that already exists.

### Setup — without Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

createdb farmhand   # needs a local Postgres instance

cp .env.example .env
# edit .env if your Postgres isn't at the default localhost:5432 farmhand/farmhand

uvicorn app.main:app --reload --port 5546
```

Then open http://localhost:5546/docs for interactive API docs (FastAPI's
auto-generated Swagger UI) — every endpoint below is browsable/testable
there without writing any client code.

## Running tests

```bash
pytest
```

The parser tests (`tests/test_parser.py`) and most of the service tests
(`tests/test_bundle_service.py`) run against the **real** sample `.3mf`
files from the mockup phase, expected at `/mnt/user-data/uploads/`. If
those aren't present (e.g. running this outside the original environment),
those tests skip rather than fail — copy the three sample files there, or
point `sample_3mf_paths` in `tests/conftest.py` at wherever you keep them,
to exercise the real parsing/versioning logic end to end.

Service tests use an in-memory SQLite database, so they don't need a real
Postgres instance running.

> **Note on this codebase's provenance**: every file here was written and
> syntax-checked in a sandboxed environment with no network access, so
> `pip install` was never actually run against it here — the parser logic
> itself WAS executed and verified against your three real files (see the
> test assertions, which are real extracted values, not guesses). The
> SQLAlchemy/FastAPI layer is correct as far as careful review can confirm,
> but hasn't been run end-to-end. Running `pytest` after your first
> `pip install` is the way to confirm it before relying on it.

## API overview

| Method | Path | Purpose |
|---|---|---|
| GET | `/printers` | List printers |
| POST | `/printers` | Register a printer (name is the unique key) |
| PATCH | `/printers/{id}` | Edit a printer — partial update (only fields present are changed; `null` clears an IP/type). Renaming is safe: see "Renaming a printer" below |
| PATCH | `/printers/{id}/decommission` | Toggle decommissioned |
| PUT | `/printers/{id}/notes` | Save the printer's notes. Send the `base_revision` the text was based on; if someone saved since, answers **409** with their current notes and changes nothing (same rules as a model's notes, shared code in `app/notes.py`) |
| GET | `/printers/{id}/bundles` | 3MF bundles locked to a printer |
| GET | `/source-models` | List STL/OBJ/STEP source models |
| POST | `/source-models` | Create a new STL folder (file optional at creation) |
| POST | `/source-models/{id}/versions` | Add a new version of a source model's geometry |
| GET | `/source-models/{id}/bundles` | 3MF bundles built from a source model |
| GET | `/source-models/{id}/versions/{v}/thumbnail` | Auto-generated thumbnail (STL only for now). Sent with `Cache-Control: no-cache` so a redrawn preview replaces the browser's copy |
| POST | `/source-models/{id}/versions/{v}/thumbnail` | Redraw this version's preview from its file with the current renderer (`{"updated": bool}`); 422 if the file isn't reachable, so a redraw never replaces a preview with nothing |
| GET | `/settings/storage` | Where STL and 3MF files are stored, whether each location is ready, free space, and how many versions still have files outside the chosen locations |
| PUT | `/settings/storage` | Choose the STL and/or 3MF folder (`stl_path`, `threemf_path`; `null` resets to the default). Validated before anything is written |
| GET | `/settings/storage/shares` | Saved NAS shares (connected or not, last error, files stored on each) and whether this container is allowed to mount |
| POST | `/settings/storage/shares` | Connect a share: `name` plus ONE `location` (`//192.168.1.50/farmhand/Projects`, `\\\\nas\\farmhand`, `smb://…`, `192.168.1.50:/volume1/farmhand`, `nfs://…`) — protocol, server and share are worked out from it — and optional `username`/`password`/`domain`/`version`. (Separate `protocol`/`server`/`share` still work.) Mounted first, saved only if that works |
| PATCH | `/settings/storage/shares/{id}` | Change a share's address (`location`) or login — tried on a scratch mount first. Blank password keeps the saved one |
| POST | `/settings/storage/shares/{id}/connect` | Retry connecting now |
| DELETE | `/settings/storage/shares/{id}?confirm=true` | Disconnect and forget a share. Refused (409) while it's a chosen storage location |
| POST | `/settings/storage/folders` | Create a folder (`parent`, `name`) on a connected share or in Farmhand's storage |
| GET | `/settings/storage/browse?path=` | Sub-folders for the folder picker, confined to the browse root |
| POST | `/settings/storage/migrate` | Move files from previous locations into the chosen ones (verified copy, then delete the original) |
| GET | `/bundles` | Every bundle (powers cross-file compare) |
| POST | `/bundles/inspect` | Read a 3MF without storing it: which printer it was sliced for, and whether that printer is registered |
| POST | `/bundles` | Upload a new 3MF bundle; gcode is optional, printer_id optional (auto-detected from the file if omitted) |
| POST | `/bundles/{id}/versions` | "Update" — new version within an existing bundle |
| GET | `/bundles/versions/{id}` | Full detail for one version, including parsed settings (what the compare view fetches) |
| GET | `/bundles/versions/{id}/thumbnail` | The 3MF's own embedded thumbnail (survives pruning) |
| DELETE | `/bundles/versions/{id}?confirm=true` | Permanently delete one 3MF version (files + settings). Deleting a bundle's last version deletes the bundle |
| DELETE | `/bundles/{id}?confirm=true` | Permanently delete a bundle and all its versions |
| DELETE | `/source-models/{id}/versions/{v}?confirm=true` | Delete one STL version's file (the folder stays) |
| DELETE | `/source-models/{id}?confirm=true&cascade=` | Delete an STL folder. Bundles sliced only from it are refused (409) unless `cascade=true`, which deletes them too; mixed-plate bundles that use other models are just unlinked |
| PATCH | `/bundles/versions/{id}/monument` | Flag/unflag a version as a monument |
| GET | `/bundles/versions/{id}/download/3mf` | Download the original 3MF (404s if pruned) |
| GET | `/bundles/versions/{id}/download/gcode` | Download the gcode (404s if none was uploaded, or if pruned) |

## Project layout

```
app/
  parsers/       # 3MF unzip + slicer-specific config parsing
  models/        # SQLAlchemy ORM models
  schemas/       # Pydantic request/response shapes
  services/      # business logic (versioning rules live here, not in routers)
  routers/       # FastAPI route definitions — thin, delegate to services
  storage.py     # local-disk file storage, swappable later
  config.py      # env-based settings
  database.py    # engine/session setup
  main.py        # app entrypoint
tests/
```


## Renaming a printer

A printer's name is also how uploads find it: a 3MF's embedded printer profile
is matched to a printer by name. Renaming is safe because matching falls back
to profile names the printer has already received files under
(`printer_service.find_by_profile_name`), and the locked-printer check on
"Update" accepts the printer's current name *or* any profile name that bundle's
earlier versions were sliced under. The flip side: picking an existing printer
by hand for a file whose profile name doesn't match it also teaches the match —
later files with that profile name will find that printer.

## Deleting

Deletes are permanent and need an explicit `confirm=true` (the web UI shows its
own confirmation first). Database rows go first, then the files on disk, so a
failure in between leaves consistent records and at worst some orphaned files.


## Storage layout

Two independently chosen roots (Storage page, saved in the `app_settings` table):

```
{stl_root}/{source_model_id}/v{n}/{file}        STL / OBJ / STEP
{threemf_root}/{bundle_id}/v{n}/{file}          3MF and gcode
{storage_root}/thumbnails/{source_models|bundles}/{id}/v{n}/thumbnail.png   always local
```

With nothing chosen they default to `{storage_root}/source_models` and
`{storage_root}/bundles`, the same layout as before. The database stores absolute
paths, so a file stays where it is when a location changes until it is moved.

- A chosen folder must be under `FARMHAND_STORAGE_BROWSE_ROOT` (default: the parent
  of `FARMHAND_STORAGE_ROOT`; `/data` in Docker) — the picker can't browse elsewhere,
  and `..`/symlink escapes are rejected.
- Chosen folders contain a `.farmhand-storage` marker; writes are refused (HTTP 503)
  when it's missing, which is what an unmounted share looks like.
- Uploads are written under a temporary name and renamed, so a share dropping
  mid-write never leaves a truncated file that looks real.
- Deletion removes only the files recorded in the database, plus the empty
  `v{n}`/`{id}` folders made for them — never a recursive delete of a folder.
- STL thumbnails are rendered on an opaque white background, solid-shaded, from every triangle: `app/thumbnails/stl_render.py` is a small depth-buffered rasterizer in numpy (no matplotlib — it needs only numpy and Pillow). Binary and ASCII STL; shading comes from the geometry, not the file's stored normals (often missing or wrong); framing fits the model's own silhouette.


## Network shares (how mounting works)

`app/mounts.py` reads a single pasted location into protocol/server/share (`parse_location`; the frontend's `location.js` mirrors it only for the live preview, and they're checked against each other), validates what a person typed, builds the `mount` command as an argument
list (never a shell string), and turns `mount`'s errors into plain-language messages.
An SMB login goes in a temporary `0600` credentials file — never on the command line and
never in the comma-separated option string. `app/services/network_shares_service.py` saves
shares in the `network_shares` table (the password is stored as-is and never returned by
the API) and `app/mount_supervisor.py` re-mounts anything unmounted every 30 s from a
background thread, so a slow NAS never delays the API starting.

Shares are mounted at `/data/nas/<name>` inside the container. This requires the
`SYS_ADMIN` capability (plus `DAC_READ_SEARCH` for SMB, which `mount.cifs` insists on) and the `cifs-utils`/`nfs-common` packages (the Dockerfile installs
them). Mounting hasn't been run against a real NAS where this was written — see the main
README.


## Scanning

`POST /source-models/scan` (read-only) lists model files in the STL folder that aren't in the
library; `POST /source-models/scan/import` adds chosen ones, **moving** each into the same layout an
upload uses (`<STL folder>/<model id>/v1/<name>`; previews go to local disk, and the version's note
records the folder it came from). The order is: draw the preview from the original, move the file
(`os.rename` within a filesystem, else a size-verified copy then delete), then save the row; if any step
fails the file is put back and nothing is left behind (`storage.move_file`, `import_scanned_file`). The
paths come from the browser, so every one is re-checked: inside the STL folder, a real non-symlink
STL/OBJ/STEP file, not already known, and a destination path short enough for the database column. The
folders a file came from are never removed. See `app/scanner.py` for what is skipped.

## Notes

`PUT /source-models/{id}/notes` with `{"notes": "...", "base_revision": N}` saves free text about a model
(max 20,000 characters; `base_revision` is the revision the text was written from, 0 if there were none). The
notes and `notes_revision` come back on every source model. If someone else saved since, the answer is
**409** with `{"detail", "current": {"notes", "notes_revision", "notes_updated_at"}}` and nothing is
overwritten. The write is a single conditional `UPDATE ... WHERE revision = base_revision` (or an insert that
collides on the primary key for a first save), so concurrent saves can't both win whatever the isolation
level. Clearing keeps the row with an empty body, so a revision number is never reused. Stored in its own
table, `source_model_notes`, so `create_all` adds it to existing databases without altering any table. NUL
characters (which PostgreSQL can't store) are removed.
