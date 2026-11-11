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
- **OrcaSlicer / Bambu Studio parser** (`app/parsers/orcaslicer.py`): reads
  `Metadata/project_settings.config` (JSON) and tells Orca from Bambu Studio
  by `3D/3dmodel.model`'s metadata. Lists (one value per filament or
  extruder) are kept joined as PrusaSlicer writes them, and any print-host
  login in the file is dropped. `slicer_family` is `orcaslicer` or
  `bambustudio`; the printer preset (`printer_settings_id`) names the printer,
  as Orca has no physical printer in a 3MF. Built against a real OrcaSlicer
  2.4.2 file.
- **Versioning engine** (`app/services/bundle_service.py`): the rolling
  5-version full-file window, monument exemption (version 1 is one), and the locked-printer
  rule (a bundle's printer can't change after creation; uploading an
  "Update" whose embedded profile doesn't match is rejected).
- **Upload flow** matching the UI decisions made in the mockup: creating a
  bundle can either take an explicit `printer_id`, or omit it entirely and
  have the printer read from the 3MF's own embedded profile (must already
  be registered under that exact name).

## What's NOT implemented yet

- Alembic migrations — currently uses `Base.metadata.create_all()` on
  startup, fine for early development, not for a production DB with data
  worth preserving across schema changes
- Auth/permissions (none — internal tool assumption carried over from the
  mockup)
- STEP viewer / three.js rendering pipeline (deferred per spec, revisit
  once this core is further along)
- Cloud file storage (currently local disk under `storage/`, behind a
  small interface in `app/storage/` so it can be swapped later)

## Setup — Docker Compose (recommended)

```bash
docker compose up --build
```

That's it — this starts Postgres and the API together, with the API on
**http://localhost:4545**. Interactive API docs (Swagger UI) are at
http://localhost:4545/docs. Data persists in named Docker volumes
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
# edit .env if your Postgres isn't at the default localhost:2727 farmhand/farmhand

uvicorn app.main:app --reload --port 4545
```

Then open http://localhost:4545/docs for interactive API docs (FastAPI's
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
| GET | `/projects` | Every project, by name: `{id, name, created_at, doc_files, cad_files, stl_files, threemf_files, source_model_ids, source_models, bundle_ids, printer_ids, parts}`. `doc_files` (its documents: any file), `cad_files`, `stl_files` and `threemf_files` (its own STLs and 3MFs, not in Models) are `[{id, name, created_at, versions: [{version, filename, size_bytes, note, uploaded_at, has_preview}]}]` (a file's `name` is its newest version's; versions newest first). A 3MF also has `printer_id`, and each of its versions `gcode_name`; an STL has `need` and `have`. `source_model_ids`, `bundle_ids` and `printer_ids` are the models, 3MFs and printers from the rest of Farmhand it uses, in the order they were added; `source_models` lists those models with `{id, need, have}`; `parts` is its BOM, `[{id, name, need, have, link, note}]` |
| POST | `/projects` | Make a project: `{name}` (spaces tidied). **409** if it's empty, over 200 characters, or another project's name (any case) |
| GET | `/projects/scan?path=` | The folders inside `path` (under the browse root, and not Farmhand's own project files folder; **422** otherwise), each as the project it would become: `{path, folders: [{name, path, files: {doc, cad, stl, threemf, gcode}, total, in_farmhand, error}]}` |
| POST | `/projects/import` | Make a project from one folder, `{path}`: named after it, its files copied in by kind (`.stl`/`.obj` as its own STLs with the subfolder as sub-component, `.3mf` for the printer it was sliced for, a `.gcode`/`.bgcode` beside a 3MF of the same name as its G-code, CAD extensions as CAD files, the rest as documents). **201** `{project_id, name, files, warnings}` (a file that couldn't come in is a warning); **409** if a project of that name is here; **422** for a folder that isn't allowed; **503** if the project files folder isn't there |
| POST | `/projects/scan-projects-folder` | Scan projects: every folder in the project files folder that isn't one of this Farmhand's projects becomes one, its files used where they are (nothing copied): another Farmhand's, from its `farmhand-project-<id>.json` records (name, files and versions, notes, sub-components, counts, parts, models and printers by name), or one dropped in by hand, sorted by kind. One named like a project here is left out. `{imported: [{project_id, name, files, warnings, repaired?}], skipped: [{name, reason}], models: [names], threemfs: [names], library_skipped: [{name, reason}]}` (the models and 3MFs another Farmhand sharing the folders has are brought in first, from their `farmhand-model-<id>.json` / `farmhand-3mf-<id>.json` records, a 3MF only once its printer is here); Load all settings runs it too, and also adds the files another Farmhand added to a project both have. 503 while the folder isn't there |
| GET | `/projects/check` | Every project file against the disk, changing nothing: `{projects, files_checked, root, error, problems: [{project_id, project, kind, file_id, version, filename, path, problem}], problems_total, unknown: [paths], unknown_total}` (a problem is a file missing, or not the size it was saved at; `unknown` are files in the project files folder no project has on record; at most 500 of each are listed) |
| GET | `/projects/{id}` | One project |
| PATCH | `/projects/{id}` | Rename it: `{name}` (the same rules) |
| DELETE | `/projects/{id}?confirm=true` | Delete a project with its own documents, CAD files, STLs and 3MFs (rows, then files). The models, 3MFs and printers it uses stay |
| POST | `/projects/{id}/doc` | Upload a document, any file (multipart `file`, optional `note`), as version 1 in `.../{project}/docs/{file}/v1/`; a picture gets a preview of itself |
| PUT | `/projects/{id}/doc/order`, `/projects/{id}/cad/order` | Arrange the project's documents (or CAD files): `{ids}`, every one of them, first to last (422 when it isn't exactly those: the list changed since it was shown). Kept in `project_doc_file_positions` / `project_cad_file_positions`; a file never arranged comes after those that were. Answers the project |
| POST | `/projects/{id}/cad` | Upload a CAD file of any kind (multipart `file`, optional `note`) as version 1, kept as `<name> ver 1.<ext>` in the project files folder, with a preview next to it when one can be made (STEP/IGES/BREP through gmsh, STL, OBJ, a Fusion file's own picture). **503** if that folder isn't there right now. Answers the project |
| POST | `/projects/{id}/stl` | Upload an STL or OBJ (multipart `file`, required `in_models`, optional `note`, optional `component`: the sub-component it goes in, from the folder it was in, `Body/Fins` for one inside another; spaces tidied, `\` taken as `/`, blank is none, at most 200 characters). `in_models=true`: it becomes a new model in Models (in the STL folder) that the project uses. `false`: the project's own, as version 1 in the project files folder (`.../{project}/stl/{file}/v1/`), with a preview. **422** for another kind of file or without `in_models`. Answers the project |
| POST | `/projects/{id}/threemf` | Upload a 3MF to the project only (multipart `file`, optional `printer_id` and `note`), as version 1 in `.../{project}/threemf/{file}/v1/`; its printer comes into the project. (One also put in Models is uploaded with `POST /bundles`, then used with `PUT .../bundles/{id}`.) **422** for another kind of file; **404** for a printer that isn't there |
| POST | `/projects/{id}/{doc\|cad\|stl\|threemf}/{file_id}/versions` | A newer version of one of its own files (multipart `file`, optional `note`); every version is kept |
| GET | `/projects/{id}/{doc\|cad\|stl\|threemf}/{file_id}/versions/{v}/download` | Download one version |
| GET | `/projects/{id}/{doc\|cad\|stl\|threemf}/{file_id}/versions/{v}/view` | The same file to open in the browser (`inline`, its own type; sandboxed so a web page or SVG can't run anything) |
| GET | `/projects/{id}/{doc\|cad\|stl\|threemf}/{file_id}/versions/{v}/preview` | Its preview (PNG); **404** when it has none |
| DELETE | `/projects/{id}/{doc\|cad\|stl\|threemf}/{file_id}/versions/{v}?confirm=true` | Delete one version's file; the last one takes the file with it. Answers the project |
| DELETE | `/projects/{id}/{doc\|cad\|stl\|threemf}/{file_id}?confirm=true` | Delete one of its own files with every version. Answers the project |
| PUT | `/projects/{id}/threemf/{file_id}/versions/{v}/gcode` | A G-code for one version of its own 3MF (multipart `gcode`, a .gcode or .bgcode), kept next to the 3MF, replacing one it had |
| GET | `/projects/{id}/threemf/{file_id}/versions/{v}/gcode` | Download it |
| POST | `/projects/{id}/threemf/{file_id}/versions/{v}/print` | Send it to the 3MF's printer and start it, as `/bundles/versions/{id}/print` (**409** while the printer is busy; **422** with no printer; **502** unreachable) |
| POST | `/projects/{id}/parts` | Add a part to the BOM: `{name, need?, have?, link?, note?}` (need 1 or more, default 1; have 0 or more, default 0; link an http(s) address, `https://` added when none is given). **422** without a name, for a bad count or a link that isn't a web address. Answers the project |
| PATCH | `/projects/{id}/parts/{part_id}` | Change a part's `name`, `need`, `have`, `link` or `note` (only the fields sent; a blank or null link or note clears it) |
| DELETE | `/projects/{id}/parts/{part_id}?confirm=true` | Remove a part from the BOM |
| POST | `/projects/{id}/parts/bom` | Upload a BOM: multipart `file` (a CSV whose first row names its columns: Part, Need, Have, Link, Notes in any order, only Part needed; Quantity counts as Need) and `replace` (true: its parts replace the BOM; false: they're added). UTF-8 (with or without Excel's byte-order mark) or Windows-1252, separated by `,` `;` or tab. Every row is checked first: **422** lists each wrong row and nothing changes. Answers `{project, added}` |
| PATCH | `/projects/{id}/source-models/{model_id}`, `/projects/{id}/stl/{file_id}` | How many prints of a model it uses, or of one of its own STLs, the project needs and has, and the sub-component it's in: `{need?, have?, component?}` (only those sent change; a blank or null `component` takes it out of any). The project answers each with `component` (null: in none); a model's is this project's only, and goes when it's taken out |
| PUT | `/projects/{id}/bundles/{bundle_id}` | Use a 3MF in the project; the printer it's for comes too. **404** for a 3MF or project that isn't there. Answers the project |
| DELETE | `/projects/{id}/bundles/{bundle_id}` | Take a 3MF out of the project (it stays, and so does its printer in the project) |
| PUT | `/projects/{id}/printers/{printer_id}` | Put a printer in the project |
| DELETE | `/projects/{id}/printers/{printer_id}` | Take a printer out of the project (it and the project's 3MFs for it stay) |
| PUT | `/projects/{id}/source-models/{model_id}` | Use a model from Models in the project (already in it: no change). **404** for a model or project that isn't there. Answers the project |
| DELETE | `/projects/{id}/source-models/{model_id}` | Take a model out of the project (the model stays in Models; nothing is deleted, so no `confirm`). Answers the project |
| GET | `/printers` | List printers |
| POST | `/printers` | Register a printer (name is the unique key) |
| GET | `/printers/discover/range` | The range Scan network starts with: `{cidr}`, the /24 of the server's own private IPv4 address, or, in a Docker container (which only sees Docker's network), the /24 most printers' IPs are in; `null` when neither is known |
| GET | `/printers/discover?cidr=192.168.1.0/24` | Printers in a private IPv4 range (10.x, 172.16–31.x, 192.168.x; up to a /22; anything else is a 422) that aren't in Farmhand yet: Klipper / Kalico, found by their Moonraker on port 7125, and Prusas, by their PrusaLink on port 80 (its `/api/version`: without the password it turns the question down with its own Digest realm, "Printer API", so it's found as `connection_type: "prusalink"`, `needs_api_key: true`, no hostname). Addresses an active printer already has are skipped; a printer found at a decommissioned one's address is listed with `decommissioned_id` / `decommissioned_name` (null otherwise), so the UI brings that one back (a PATCH of it) instead of adding it again. Each printer's `/machine/system_info` interfaces give `link` (`wired` / `wireless` by interface name, e.g. `eth0` / `wlan0`; null when unknown) and its `wired_ip` / `wireless_ip`. A printer answering on both is listed once, at its wired IP, and one whose other IP is already in Farmhand is skipped. Nothing is added; each answer is `{ip, connection_type, address, web_url, hostname, firmware, version, state, needs_api_key, link, wired_ip, wireless_ip, decommissioned_id, decommissioned_name}` |
| PATCH | `/printers/{id}` | Edit a printer — partial update (only fields present are changed; `null` clears an IP/type). Renaming is safe: see "Renaming a printer" below |
| DELETE | `/printers/{id}?confirm=true` | Delete a decommissioned printer with its print history, notes, connection, printer profiles, parts and maintenance. 409 while it's active or still has 3MF files (the message says which) |
| PUT | `/printers/{id}/notes` | Save the printer's notes. Send the `base_revision` the text was based on; if someone saved since, answers **409** with their current notes and changes nothing (same rules as a model's notes, shared code in `app/notes.py`) |
| GET | `/printers/{id}/bundles` | 3MF bundles locked to a printer |
| GET | `/printers/{id}/progress` | How far along the print running now is, for Monitor's cameras: `{state: "printing" \| "paused" \| null, progress: 0-100 \| null, file, error}`, from Klipper or PrusaLink. Never fails: `error` says why the printer couldn't be asked |
| GET | `/printers/{id}/prusalink/password` | A PrusaLink printer's saved password, for the Edit form's **Show**: `{password}` (null when none is saved; 409 for a printer not on PrusaLink). It's never part of the printer itself (`has_prusalink_password` only) |
| POST | `/printers/{id}/sub-printers` | Add a printer profile (one of the printer's presets in PrusaSlicer) by hand: `{name}`. **409** if it already has one by that name. Printer profiles are also added on their own when a 3MF sliced with a new preset (`printer_settings_id`) is uploaded, and each 3MF version says which one it was sliced with (`sub_printer_id`, `sub_printer_name`). Answers the printer, whose `sub_printers` lists them |
| GET | `/printers/{id}/sub-printers/{sub_id}/settings-copy` | A copied printer profile's printer settings, as its original had them when it was copied (from its newest 3MF): `{copied_from, from_file, copied_at, settings}`. Shown in its Printer Settings until a 3MF sliced with it is uploaded. **404** when it has none (it isn't a copy, or nothing had been sliced with the original). A printer profile says `settings_copied_from` when it has them |
| POST | `/printers/{id}/sub-printers/{sub_id}/copy` | A copy of a printer profile, with its parts and its printer settings (a snapshot, see `settings-copy`): `{name?}`. Without a name it's called `<its name> - copy` (`- copy 2`, `- copy 3`... when that's taken). Its 3MFs, its `aliases` and being the default stay with the original. **409** if the printer already has one by that name. Answers the printer |
| PATCH | `/printers/{id}/sub-printers/{sub_id}` | Rename a printer profile: `{name}`. Its 3MFs stay linked, and its old name is kept in its `aliases` (3MFs sliced with that preset still go to it). **409** if another of the printer's has that name |
| DELETE | `/printers/{id}/sub-printers/{sub_id}?confirm=true` | Remove a printer profile and the parts written down for it. Its 3MFs stay, with no printer profile (and if it was the default, there's none) |
| PUT | `/printers/{id}/default-sub-printer` | The printer's default printer profile: `{sub_printer_id}` (one of its own, else **404**), or `{sub_printer_id: null}` for none. The UI picks it for every 3MF uploaded to the printer, whatever its preset (an upload that names no printer profile still goes by the preset). Answers the printer, with `default_sub_printer_id` |
| GET | `/printers/{id}/sub-printers/{sub_id}/parts` | The parts fitted to a printer profile (its Printer parts page), in the order added: `[{id, part, make, model, installed_on, note}]` |
| PUT | `/printers/{id}/sub-printers/{sub_id}/parts` | Save the whole list at once (the Printer parts page's Save): `[{id?, part, make?, model?, installed_on?, note?, in_name?}]`. A part with its `id` is changed, one without is added (after the rest), one left out is removed, which needs `?confirm=true` (409 without). All of it or nothing. Answers the list |
| POST | `/printers/{id}/sub-printers/{sub_id}/parts` | Write down a part: `{part, make?, model?, installed_on? (YYYY-MM-DD), note?}`. Answers the list as it now stands |
| PUT | `/printers/{id}/sub-printers/{sub_id}/parts/{part_id}` | Change a part (every field is replaced; blank clears). Answers the list |
| DELETE | `/printers/{id}/sub-printers/{sub_id}/parts/{part_id}?confirm=true` | Remove a part. Answers the list |
| GET | `/source-models` | List STL/OBJ/STEP source models |
| POST | `/source-models` | Create a new STL folder (file optional at creation) |
| POST | `/source-models/{id}/versions` | Add a new version of a source model's geometry |
| GET | `/source-models/{id}/bundles` | 3MF bundles built from a source model |
| GET | `/source-models/{id}/versions/{v}/thumbnail` | Auto-generated thumbnail (STL only for now). Sent with `Cache-Control: no-cache` so a redrawn preview replaces the browser's copy |
| POST | `/source-models/{id}/versions/{v}/thumbnail` | Redraw this version's preview from its file with the current renderer (`{"updated": bool}`); 422 if the file isn't reachable, so a redraw never replaces a preview with nothing |
| GET | `/settings/storage` | Where STL and 3MF files are stored, whether each location is ready, free space, and how many versions still have files outside the chosen locations |
| PUT | `/settings/storage` | Choose the STL and/or 3MF folder (`stl_path`, `threemf_path`; `null` resets to the default). Validated before anything is written |
| GET | `/settings/storage/save-location` | The save location as typed (`address`, null until set), its `share` as the shares list has one (connected or not, why not, login without the password, SMB version; null until set), `capability` (may this container mount shares), and the folder each kind of file goes to now: `folders: {stl, threemf, project, farm_cost, config}` |
| PUT | `/settings/storage/save-location` | One place on the NAS for everything: `{address, username?, password?, domain?, version?}` (a blank password keeps the saved one; a changed username, domain or version is tried on a scratch mount first). Connects to it, reusing the share already there (also for a folder inside it) or adding one, mounted first; then uses or makes `STL`, `3MF`, `Projects`, `farm-cost`, `stream` and `farmhand-configs` inside it (an existing folder of that name is used whatever its capitals) and points every folder setting at them. `config_choice` is set when farmhand-configs already holds saved settings: nothing is written there until the person chooses to load or replace them. 422 with the NAS's reason when it can't connect |
| GET | `/settings/storage/shares` | Saved NAS shares (connected or not, last error, files stored on each) and whether this container is allowed to mount |
| POST | `/settings/storage/shares` | Connect a share: `name` plus ONE `location` (`//192.168.1.50/farmhand/Projects`, `\\\\nas\\farmhand`, `smb://…`, `192.168.1.50:/volume1/farmhand`, `nfs://…`) — protocol, server and share are worked out from it — and optional `username`/`password`/`domain`/`version`. (Separate `protocol`/`server`/`share` still work.) Mounted first, saved only if that works |
| PATCH | `/settings/storage/shares/{id}` | Change a share's address (`location`) or login — tried on a scratch mount first. Blank password keeps the saved one |
| POST | `/settings/storage/shares/{id}/connect` | Retry connecting now |
| DELETE | `/settings/storage/shares/{id}?confirm=true` | Disconnect and forget a share. Refused (409) while it's a chosen storage location |
| POST | `/settings/storage/folders` | Create a folder (`parent`, `name`) on a connected share or in Farmhand's storage |
| GET | `/settings/storage/browse?path=` | Sub-folders for the folder picker, confined to the browse root |
| POST | `/settings/storage/migrate` | Move files from previous locations into the chosen ones (verified copy, then delete the original) |
| GET | `/bundles` | Every bundle (powers cross-file compare) |
| POST | `/bundles/inspect` | Read a 3MF without storing it: which printer it was sliced for, whether that printer is registered, and its printer preset (`printer_preset_name`) |
| POST | `/bundles` | Upload a new 3MF bundle; gcode is optional, printer_id optional (auto-detected from the file if omitted). Which printer profile it goes to: `sub_printer_id` (one of the printer's) or `new_sub_printer_name` (a new one, or the printer's one by that name); neither = the one its preset goes to (a printer profile with that preset in its `aliases`, else the one called that, else a new one). A preset put with a printer profile by another name is added to its `aliases`. **422** for another printer's printer profile |
| POST | `/bundles/{id}/versions` | "Update" — new version within an existing bundle; takes the same `sub_printer_id` / `new_sub_printer_name` |
| GET | `/bundles/versions/{id}` | Full detail for one version, including parsed settings (what the compare view fetches) |
| GET | `/bundles/versions/{id}/thumbnail` | The 3MF's own embedded thumbnail (survives pruning) |
| DELETE | `/bundles/versions/{id}?confirm=true` | Permanently delete one 3MF version (files + settings). Deleting a bundle's last version deletes the bundle |
| DELETE | `/bundles/{id}?confirm=true` | Permanently delete a bundle and all its versions |
| DELETE | `/source-models/{id}/versions/{v}?confirm=true` | Delete one STL version's file (the folder stays) |
| DELETE | `/source-models/{id}?confirm=true&cascade=` | Delete an STL folder. Bundles sliced only from it are refused (409) unless `cascade=true`, which deletes them too; mixed-plate bundles that use other models are just unlinked |
| GET | `/bundles/versions/{id}/download/3mf` | Download the original 3MF (404s if pruned) |
| GET | `/bundles/versions/{id}/download/gcode` | Download the gcode (404s if none was uploaded, or if pruned) |
| GET | `/farm-cost?tz=` | The filament each printer used, by month in the viewer's time zone: `{printers: [{printer_id, months: [{key, prints, grams, filament_cost, unweighed, uncosted}], days, energy_days: [{key, whole, partial}]}], records: {folder, problem, saved}}` (the Farm cost page; `days`: the same as `months` per day, key `2026-10-05`; `energy_days`: the power meter's rise per day, for a printer clicked while looking at a month; `records`: the farm cost folder, where each month's CSV is saved once it's over) |
| GET | `/farm-cost/location` | Where each month's Farm cost record is saved: `{path, is_default, default_path, status}` (default: "farm-cost" in the folder above the STL folder; one still called "farm cost" is renamed to it when next written to) |
| PUT | `/farm-cost/location` | `{path}` chooses that folder (it gets Farmhand's marker; 422 says why one can't be used); `{path: null}` goes back to the default |
| GET | `/stream` | The Stream page: `{settings: {destination, cols, rows, cells, cameras, show_status, layout, resolution, seconds_all, seconds_each, border_color, title, description, key_set, key_from_youtube, youtube}, status: {live, on_air, started_at, destination, cameras, error, title, youtube}, destinations: [{key, label}], resolutions: [{key, label}], fonts: [{key, label, generic}] (what a square's words can be written in), media: {path, windows_path (the folder as Windows reaches it over the network, `\\server\share\...`, or null when it isn't on an SMB share), images: [file names], slideshows: [{name, images}], music: [MP3 file names], error} (the stream folder, as last read: see `POST /stream/scan`), youtube: {client_set, client_id, signed_in, channel, signing_in: {user_code, verification_url} \| null, error}}`. `destination` is `youtube` (the only one for now: Twitch is to come back later; a setup saved with `twitch` is read as `youtube`, and sending it is a 422); the grid is `cols` x `rows` (1 to 5 each) squares, `cells` one per square, row by row: `{"camera": "printer id:camera name"}` (as Monitor names them), a card `{"background": "#RRGGBB" | null (the stream's), "image": a picture's file name | null, "slideshow": a slideshow's folder name | null, "seconds": 3 to 3600, "text": up to 500 characters ("" none), "color", "font": one of `fonts`' keys (Play unless chosen), "band": a dark band behind the words (false unless chosen), "picture_box": {x, y, w, h} the box the picture is fitted into, "text_box": {x, y, size} the words' centre and height (all parts of the square, 0 to 1; kept inside it), "picture_boxes": a slideshow's pictures' own size and place, `{picture's file name: picture_box}` (the others keep `picture_box`), "captions": a slideshow's pictures' own words, `{picture's file name: {text, text_box}}`, each shown instead of `text` while its picture is (over 500 characters: 422), "layers": more pictures and pieces of text over it, drawn in order, each placed on its own: `{"type": "picture", "image": a picture's file name, "box": {x, y, w, h}}` or `{"type": "text", "text", "box": {x, y, size}, "font", "color", "band"}` (up to 12; a piece of text over 500 characters: 422), "slide_layers": a slideshow's screens' own, `{picture's file name or "blank:N": [layers]}`, each drawn only while that screen is}`, or `null` (empty); a camera may have its own `"background"` round it, and its own words: `"show_words": false` (none on it), `"words_size"` (0.02 to 0.3 of its square's height; none: sized to fit), `"words_color"`, `"words_font"` (only what differs from the usual is kept); `background` is the stream's own colour; `font` and `color` are the stream's words' (every card's and camera's that has none of its own: Play and `#FFFFFF` unless chosen); `music` plays the stream folder's MP3s on the stream, starting with it (true, the default; false: silence), `music_volume` 0 to 100 (50; squared, so 50 is -12 dB), `music_shuffle` a new order each round (true; false: name order); `status.music` the music going out while live, `{on, playing, track, at}` (`track` its file name, `at` seconds into it), null otherwise; `enabled` is the page's switch (false: a live stream stops, and going live is refused with a 422 until it's true again); `cameras` is the cameras in square order; `border_color` the `#RRGGBB` round each square; `resolution` is `1080p` (the default), `720p` or `1440p` (2K; `resolutions` lists them with their names); `layout` is `grid` (all at once) or `cycle` (taking turns: all for `seconds_all`, 0 = never, then each for `seconds_each`); `live` means it's meant to be streaming, `on_air` that ffmpeg is running right now; `error` why it last stopped (it's tried again every 10 s); `status.server_time` the server's time of day (slideshows and taking turns count from it, on the stream and on the page, so they show the same picture), `status.running_for` how long the picture going out has run, in seconds (its slideshows and taking turns count from its start; null while it isn't going out), `status.encoder` `nvenc` or `cpu` while live; `status.delay` the buffer before YouTube while live, `{seconds, held, filling}` (`held`: seconds held now; `filling`: still collecting it, nothing sent yet); `delay` the seconds it holds (0 to 120, 60 unless chosen; a new one applies when going live); `settings.youtube` the video's YouTube settings, `{privacy: public \| unlisted \| private (public unless chosen), tags: [words], category: "28" \| "27" \| "26" \| "22" \| "24" \| "20" (Science & Technology unless chosen), made_for_kids, latency: normal \| low \| ultraLow, dvr, auto_start, auto_stop}`; `key_from_youtube` Farmhand has a stream of its own on the signed-in channel, so its key comes from YouTube; `status.title` how making or changing the YouTube broadcast went (`{state: done \| failed, message}`, null when there's nothing to say); `status.youtube`, signed in and live, the broadcast Farmhand made and YouTube's word on it, read at most once a minute: `{watch_url, studio_url, state (its lifeCycleStatus: ready, live, complete...), health: good \| ok \| bad \| noData \| null, issues: [YouTube's warnings], viewers (concurrent, null until live)}`. A YouTube sign-in under way is checked with Google on each ask. The stream key, client secret and YouTube token are never answered |
| PUT | `/stream` | Save `{destination?, cols?, rows?, cells?, cameras?, border_color?, background?, font?, color?, enabled?, music?, music_volume?, music_shuffle?, delay?, youtube?, show_status?, layout?, resolution?, seconds_all?, seconds_each?, title?, description?, stream_key?, clear_key?}` (only those sent change; the grid comes as `cols`, `rows` and `cells` together, or as `cameras`, a list that makes a grid just big enough for them in that order; a blank `stream_key` keeps the saved one; an empty title or description leaves YouTube's own). **422** for a key that doesn't look like one, a grid over 5x5 or cells that don't fill it, a camera in two squares, a card with both a picture and a slideshow or a name a file can't have, its text over 500 characters, a slideshow's seconds out of 3 to 3600, a border that isn't `#RRGGBB`, over 25 cameras, another destination or layout, seconds out of range (all 0–3600, each 3–3600), a music volume out of 0 to 100, a delay out of 0 to 120 seconds, a title over 100 or description over 5000 characters, or `<` `>` in them; in `youtube` (only what's sent changes) a privacy, latency or category not listed, or tags with `<` `>` or over 500 characters together. While live, a change to the picture hands over to it: a new picture ffmpeg starts beside the one going out and takes over at its first keyframe, on the same connection to YouTube (the music's settings are followed at once; a new key or destination starts afresh); a new title, description or `youtube` setting is set on the broadcast at once (`videos.update`: snippet and status). Kept in `app_settings`; the settings copy gets it as `stream-setup.json` (cameras by printer name), never the stream key, the Google client secret or the YouTube sign-in, and Load all puts it back |
| POST | `/stream/start` | Go live: ffmpeg (in the API's container) reads each chosen camera (a Mainsail MJPEG stream, plain or adaptive; camera-streamer's MJPEG; go2rtc on the printer over its RTSP port 8554; or a Buddy3D's RTSP), lays them out in a grid at the chosen `resolution` (`720p`, `1080p` or `1440p` for 2K, at 2.5, 2.5 or 4.5 Mbit/s, as YouTube advises at 15 fps) and 15 fps (taking turns: a switch lets through only the camera whose turn it is, which alone is enlarged, and a second switch chooses it or the grid, moved by a day's timetable after which ffmpeg starts again), writes each printer's print under its camera when `show_status`, adds the sound on its stdin (raw 44.1 kHz stereo, fed as it plays by Farmhand's own music player: the `music` folder's MP3s round and round, shuffled each round when `music_shuffle`, at `music_volume`, or silence), and hands it (MPEG-TS) to a second ffmpeg, the sender, which holds the one connection over RTMPS for as long as it's live and passes the stream on as it is (`-c copy`), after holding back the chosen `delay`. Signed in to YouTube, the key comes from Farmhand's own stream on the channel (`liveStreams`, made once with variable resolution and kept as `youtube_stream_id`), and a new broadcast is made first (`liveBroadcasts.insert` from the title, description and `youtube` settings, `bind` to that stream, and `videos.update` for its tags and category); it starts by itself when the video arrives (`auto_start`). **422** says why not: not signed in and no key, YouTube refusing the broadcast (its reason), no cameras, ffmpeg missing, or a camera that can't be read (WebRTC only, or not answering) |
| POST | `/stream/stop` | Stop streaming. Signed in, the broadcast is ended on YouTube (`transition` to complete), or deleted when it never went live |
| POST | `/stream/scan` | Read the stream folder again (pictures copied in or taken out by hand) and answer the page. The folder is otherwise only read after a change made through Farmhand or when it's moved, never every time the page looks |
| GET | `/stream/location` | Where the stream folder is: `{path, is_default, default_path, status}` (default: "stream" in the folder above the STL folder). Its `images` folder holds single pictures, each folder in its `slideshows` folder a slideshow, its `music` folder the stream's MP3s |
| PUT | `/stream/location` | `{path}` chooses that folder (it gets Farmhand's marker; 422 says why one can't be used); `{path: null}` goes back to the default. Kept in the settings copy |
| GET | `/stream/pictures/{name}` | A single picture from the stream folder; **404** when it isn't there; **503** while the folder isn't available |
| POST | `/stream/pictures` | Upload pictures (multipart `files`: PNG, JPEG or WebP, under 10 MB each) into `images`, a second of the same name numbered. **201**, answering the page |
| DELETE | `/stream/pictures/{name}?confirm=true` | Delete a picture's file. Squares showing it keep their colour and words |
| POST | `/stream/slideshows` | A new, empty slideshow: `{name}`, a folder in `slideshows` (unique in any case). **201** |
| PUT | `/stream/slideshows/{name}` | Rename a slideshow: `{name}`, the new name. Its folder in `slideshows` is renamed (pictures and order go with it), and every square showing it, on the Stream page and in saved layouts, follows. Only the case may change. **404** when it isn't there, **422** for a name another slideshow has (any case) or one a folder can't have. While live and it's shown, the stream starts again |
| POST | `/stream/slideshows/{name}/blanks` | A blank screen at the end of a slideshow (no picture: the square's colour and its own words, `captions["blank:N"]`), kept in its order as `blank:N`; moved with `order` and deleted with `DELETE …/pictures/blank:N`. **201** |
| PUT | `/stream/slideshows/{name}/order` | `{order: [picture names]}`: the slideshow's own order, kept in its folder (`.farmhand-order.json`); pictures left out keep their place after these, and ones added later go on the end. **422** for a name that isn't one of its pictures. While live and it's shown, the stream starts again |
| DELETE | `/stream/slideshows/{name}?confirm=true` | Delete a slideshow: its pictures, then its folder (left, with a 422, when it holds anything else) |
| GET | `/stream/fonts/{key}` | One of the stream's fonts (TTF or OTF), for the page to show a square's words as the stream writes them; **404** when this Farmhand hasn't got it (the stream then writes in DejaVu Sans, which is always there) |
| GET | `/stream/slideshows/{name}/pictures/{picture}` | A picture of a slideshow |
| POST | `/stream/slideshows/{name}/pictures` | Upload pictures into a slideshow (multipart `files`). While live and it's shown, the stream starts again |
| DELETE | `/stream/slideshows/{name}/pictures/{picture}?confirm=true` | Delete one picture of a slideshow |
| GET | `/stream/music/{name}` | A track of the music (`audio/mpeg`), for the page to play |
| POST | `/stream/music/{play\|pause\|next\|back}` | The music going out while live: play, pause (silence, keeping its place), the next track, or back (the track from its start; in its first 3 seconds the one before). At once, without starting the stream again. **422** when not live or the music is off |
| POST | `/stream/music` | Upload MP3s into the stream folder's `music` folder (multipart `files`, under 50 MB each; a name there already is numbered). **422** for anything but an MP3. Tracks added while live join the music's next round. **201** |
| DELETE | `/stream/music/{name}?confirm=true` | Delete a track's file |
| PUT | `/stream/youtube` | The Google OAuth client to sign in to YouTube with (type "TVs and Limited Input devices"): `{client_id, client_secret?}` (a blank secret keeps the saved one for the same client ID; a different client ID signs out). **422** for one that doesn't look right |
| POST | `/stream/youtube/sign-in` | Start Google's sign-in for devices: `youtube.signing_in` gives the code to enter at google.com/device; `GET /stream` finishes it once entered. **422** with no client, or Google's own reason |
| POST | `/stream/youtube/sign-out` | `{forget_client?}`: forget the YouTube sign-in (Google is told to revoke it too), and the client as well when asked |
| POST | `/stream/youtube/apply` | Set the saved title, description and YouTube settings on the broadcast Farmhand made now; with none (live on a pasted key), the title and description on the channel's active broadcast (`liveBroadcasts.list` active, then `videos.update` of its snippet, keeping its category and tags). `status.title` says how it went; **422** when not signed in or there's nothing to set |

## Project layout

```
app/
  parsers/       # 3MF unzip + slicer-specific config parsing
  models/        # SQLAlchemy ORM models
  schemas/       # Pydantic request/response shapes
  services/      # business logic (versioning rules live here, not in routers)
  routers/       # FastAPI route definitions — thin, delegate to services
  storage/       # local-disk file storage, swappable later
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
{project_root}/{project_id}/docs/{doc_id}/v{n}/{file}  a project's documents (every version kept)
{project_root}/{project_id}/cad/{cad_id}/v{n}/{file}   a project's CAD files (every version kept)
{project_root}/{project_id}/stl/{stl_id}/v{n}/{file}   its own STLs (not in Models)
{project_root}/{project_id}/threemf/{file_id}/v{n}/{file}  its own 3MFs (not in Models), and their G-code
{file}.png                                      its preview, next to it (and nowhere else)
```

A pruned 3MF version's preview stays where the 3MF was. Previews the app kept itself before
(`{storage_root}/thumbnails/...`) are moved out next to their files by `services/previews.py`.

With nothing chosen they default to `{storage_root}/source_models`,
`{storage_root}/bundles` and `{storage_root}/projects`. No two may overlap. The database stores absolute
paths, so a file stays where it is when a location changes until it is moved.

- `FARMHAND_STREAM_ENCODER`: how the Stream page's picture is compressed: `auto` (the default: an NVIDIA card's
  encoder, NVENC, when a moment's test through it works, else the processor's libx264), `nvenc` or `cpu`. The stream's
  status says which (`status.encoder`) while live. See the README for sharing a card into a Proxmox container.
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

`app/mounts.py` reads a single pasted location into protocol/server/share (`parse_location`), validates what a person typed, builds the `mount` command as an argument
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
