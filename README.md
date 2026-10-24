# Farmhand

Read-only cataloging and versioning system for a 3D print farm's 3MF
files. Backend (FastAPI/SQLAlchemy/PostgreSQL) in `backend/`, frontend
(React/Vite) in `frontend/`.

## Run everything

```bash
docker compose up --build
```

- Frontend: **http://localhost:3636**
- API: **http://localhost:5546** (docs at `/docs`)
- Postgres: `localhost:5432` (user/pass/db all `farmhand`)

The frontend starts up and immediately asks the API for printers/models/
bundles — on a brand-new database that's an empty archive, which is a
valid (if boring) state. Load the real farm data it was built against:

```bash
docker compose exec api python -m app.seed
```

Then refresh the frontend — 2 printers, 3 STL source models (with real
auto-generated thumbnails), and 3 real 3MF bundles (including the
mixed-plate Frog case) should appear.

## What's wired up vs. what's still a stub

**Real, working, end to end:**
- Browsing printers and STL folders, drilling into 3MF version history
- The 3MF settings viewer (PrusaSlicer-tab-style) and the cross-file
  compare/diff — both fetch real parsed settings from the API per version
- Uploading a new STL/OBJ/STEP source model
- Uploading a new 3MF bundle, either to an existing source model or a
  newly-created one. Dropping the file reads its embedded printer profile:
  if that printer is registered it's used automatically; if not, you choose
  between creating it from the file (named exactly as the profile, so later
  uploads match) or picking an existing printer. gcode is optional.
- Downloading a bundle's `.3mf` (grays out once a version's files have
  been pruned by the rolling window) and a source model's geometry file
- Connecting a NAS (SMB or NFS) and choosing where files are stored — separately
  for the STL files and for the 3MF/gcode files — entirely from the **Storage**
  page: add the share, then pick or create folders on it (see "Network storage")
- **Versions.** A newer 3MF or STL becomes a *new version* of the entry it replaces, shown
  **above** the older ones (see "Versions" below).
- **The Models list** is a two-column list (one column on a narrow screen), **sortable**
  by name, date added, number of 3MF files, number of printers, or type, in either
  direction. Names sort naturally (Part 2 before Part 10), and your choice is remembered.
- **Solid STL previews.** Previews are drawn from *every* triangle of the model, in solid
  shading, on white — binary and ASCII STL both. (Earlier versions thinned out detailed
  models to save time, which left them see-through. After updating, press **Redraw
  previews** on the Models page once to redraw the ones already made; your files aren't
  touched.)
- **Scan STL folder** (Models page): finds model files that were put into the STL
  folder from outside Farmhand, and adds the ones you tick to the library (see
  "Scanning the STL folder")
- Editing a printer (name, type, IPs, decommissioned) from its page
- Deleting — always behind a confirmation that says exactly what will go:
  - a single 3MF version (trash icon on its row), or a whole 3MF with all its
    versions (trash icon in its header). Deleting a bundle's last version
    removes the whole bundle. Monument versions can be deleted too; the
    dialog warns first.
  - a single STL version (trash icon on its row — the folder stays, and can
    have a file added again), or a whole STL folder ("Delete folder"). 3MFs
    that were sliced *only* from that folder are deleted with it (the dialog
    lists them); mixed-plate 3MFs that also use other models are kept, just
    unlinked from it.
  - Deleting removes the stored files and parsed settings for good.
  Note: deleting a bundle's newest version and then uploading again reuses
  that version number.

**Not wired into the UI yet** (the API supports these, nothing calls them):
- Monument flagging/unflagging (`PATCH /bundles/versions/{id}/monument`)
  — the UI shows the monument star read-only, no toggle control yet.
- Deleting printers (retire one with "Decommissioned" instead — its history
  stays). Printers can be added from the Printers page or straight from a
  3MF upload.

## Project layout

```
backend/     FastAPI + SQLAlchemy + the real 3MF parser — see backend/README.md
frontend/    React + Vite, talks to the backend over HTTP
docker-compose.yml   brings up Postgres + both services together
```

## Local dev without Docker

Backend: see `backend/README.md`'s non-Docker instructions (remember to
pass `--port 5546`).

Frontend:
```bash
cd frontend
npm install
VITE_API_BASE=http://localhost:5546 npm run dev
```
Vite's dev server also runs on 3636 (configured in `vite.config.js`).

## Honest limitations

This was built and syntax/dependency-verified in a sandboxed environment
with no network access — `npm install` and `docker build` were never
actually run here. What WAS verified:
- Every backend Python file compiles; the parser and versioning-engine
  logic was traced by hand and partially executed directly (see
  `backend/README.md`)
- Every frontend file was bundled with esbuild (external-ing only the
  two packages that need `npm install`, react and lucide-react) with
  zero errors — this confirms all imports/exports resolve and the JSX is
  syntactically valid across the whole dependency graph, which is most of
  what a first `npm run dev` would catch

What wasn't verified: an actual browser render, an actual network
round-trip between frontend and backend, and `docker compose up` itself.
Treat the first real run as the final check, same as the backend.


## Versions

A newer file becomes a **new version** of the entry it replaces, shown **above** the older ones.
Farmhand recognises a re-upload the way you'd expect — by its **file name** — so the ordinary
upload buttons just work:

- **Upload STL** with a name that's already in the library asks whether it's a newer version
  of that model (the default) or a separate one. A new version can carry a short "what changed"
  note.
- **Upload 3MF**: if the printer the file was sliced for already has a 3MF with the **same file
  name**, the form offers "New version of …" (the default) — even before you've picked a model,
  and whichever model it belongs to. A re-sliced file under a *new* name is also offered as a
  new version of the model's entry on that printer. Say "A separate 3MF" if it really is a
  different file.
- Naming a **new STL folder** after one that already exists is flagged, with one click to use
  the existing folder instead.
- Every 3MF entry also has a **New version** button (model page and printer page), and the
  Model file card has one for the STL, for when the new file has a different name.

Notes:
- An entry is locked to its printer. A file sliced for a different printer is refused, with
  the reason, rather than quietly filed in the wrong place.
- Only the most recent versions keep their full files (the 3MF and gcode); older ones keep
  their parsed settings — and anything flagged as a monument is kept in full.
- A new version is not a monument; the first one an entry ever had is.

**What you see.** Versions run newest to oldest, top to bottom, whatever order the server
returns them in. Entries on a model page are grouped by printer, and under each printer the most
recently updated comes first; a printer's own page lists its entries newest first.

**Collapsing the versions.** Any entry with more than one version has a labelled button right
under its newest version: **Hide 3 older versions** / **Show 3 older versions**. Collapsed, an entry
shows just its **most recent 3MF** (with all its own buttons), and the header still says how many
versions there are. Clicking the entry's header does the same. **Collapse all versions / Expand all
versions** (beside *Upload 3MF*) does every entry on the page at once, on both the model page and the
printer page.
- An entry with up to 3 versions starts expanded; a longer history starts collapsed. Once you've
  opened or closed an entry that choice is **remembered in this browser** — across reloads, and
  between the model page and the printer page — even if the entry later gains versions.
- A version you've picked for compare stays picked while its entry is collapsed (the tray still
  lists it, and the entry keeps its highlight).
- Only entries that still exist are remembered; a damaged saved state is ignored.

## Appearance and settings

**Appearance** is its own item in the left-hand menu, directly below **Storage**. The **Settings
location** (where a copy of the settings is kept on the network) is on the Storage page itself,
since it's about where things are stored. Nothing is on the right-hand side.

### Appearance

- **Colour scheme:** *Farmhand* (the default, with brighter, whiter text), *Classic grey* (the
  original softer greys), *High contrast* (pure white on black), *Midnight blue*, *Violet* and
  *Light* (dark text on a light background). Each card previews the scheme in its own colours.
- **Text brightness:** pulls all the text toward white (or, on Light, toward black) — from the
  scheme's own text at 0% to as bright as it goes at 100%.
- **Font:** Archivo, your system's font, Verdana, Arial, **Play**, or monospace. Play is bundled
  with the app (served by Farmhand itself, open-source OFL licence), so it needs no internet.
- **Text size:** Small, Default, Large or Extra large (up to 25% bigger).
- **Reset to defaults** puts everything back. A preview shows the text and colours side by side.

Changes are a **live preview**: the whole page takes on the new look the moment you choose it, but
nothing is kept until you press **Save**. **Discard changes** goes back to the saved look, and
the page says "Not saved yet" while there's a difference. Leaving the page (or reloading)
without saving undoes the preview. **Reset to defaults** is also a preview until saved. Nothing
you've selected elsewhere (like versions picked for compare) is lost.

The schemes are checked for legibility: `npm run check:themes` measures the contrast of every
text colour on every surface it's drawn on (WCAG AA, 4.5:1) and fails if any scheme falls short.
The original grey is kept exactly as it was and isn't held to the check — its quietest text
measures about 2.6:1, which is why the default changed. The colours live in
`frontend/src/palettes.js`, if you want to add a scheme.

### Where settings are kept

Farmhand's settings are: the look of the site (above), display preferences (the Models sort
order), and your storage setup (the STL and 3MF folders and the network shares).

- **On the server, always.** They're kept in Farmhand's database, so every browser and device
  shows the same look and order — change it on one, it changes on all.
- **Plus a copy on the network folder you choose.** Under **Settings location**, press **Choose
  folder…**, jump to a share and pick (or make) a folder. Farmhand writes
  `farmhand-config.json` there straight away and **after every change**, so the settings
  survive a rebuild or a lost database.
- **Passwords are never written to it.** A share's login has to be known before the share can be
  mounted, so it couldn't live only on the share anyway. The file lists each share's name,
  address and login *name*; a restored share comes back saved but not connected, and says it
  needs its password (use **Edit** on it).
- **A folder that already holds settings is never overwritten without asking.** Pointing at one
  asks: *Use those settings* (restore them), or *Replace with current settings*. Until you
  choose, nothing is changed. A damaged file can only be replaced.
- **Restore** (also offered as a button once a folder is chosen) loads the file back: the look,
  the display preferences, the STL/3MF folders (even if their share hasn't reconnected yet — uploads
  stay refused until it's really there) and any shares not already present. It's safe to run twice.
- **If the share is down** the settings are still saved on the server, the page says the copy
  couldn't be updated and why, and nothing is written into the empty folder underneath. **Save a
  copy now** catches it up once the share is back.
- **Use the server only** stops the copying; nothing on the network is ever deleted.

The folder must be on a connected share or in Farmhand's own storage — the same rule as the file
folders. After a total loss: re-add the share, choose the same settings folder, and pick *Use
those settings*.

## Notes on a model, and on a printer

Every model page has a **Notes** section, between the model file and its 3MF files, for
anything worth remembering about the model as a whole: print settings that work, where it came
from, its licence, reminders. It's plain text (up to 20,000 characters); what you type is shown
exactly as typed and never treated as HTML.

- **Write, then press Save** (or **Ctrl/⌘ + S**). **Discard changes** goes back to what's saved.
  The box has an amber outline and says *Unsaved changes* while they're pending. Emptying the box
  and saving clears the notes.
- **Typing isn't lost.** If you leave the page, or reload, what you'd typed is kept as a draft in
  that browser and restored (*Restored your unsaved draft*). The browser also asks before you
  close a tab that has unsaved notes.
- **Two people can't silently overwrite each other.** Every save says which version of the notes
  it started from. If someone else saved in the meantime, nothing is overwritten: you see their
  version beside yours and choose *Use their version* or *Keep mine and overwrite theirs*. This
  holds even if two saves arrive at the very same instant — the database lets exactly one through.
- **Notes start collapsed.** Every model's and printer's notes open folded down to their **first two
  lines** (as they look on screen, so a long paragraph counts as two lines too, with a "…" when
  there's more) — or *No notes yet. Click to add some.* when there are none. **Expand** (or clicking
  the preview, which also puts the cursor in the notes) opens the editor; **Collapse** folds it again.
  Each choice is remembered for that model or printer in that browser, so one you've opened stays
  open and one you've never touched stays collapsed. Folding never loses anything: unsaved edits are
  kept, and an unsaved draft restored from last time shows in the folded view — its first two lines,
  flagged *Restored your unsaved draft … Expand to review* — so it can't be missed. Save/Discard work
  as before once you expand. (A browser that holds a "folded" choice from an earlier version keeps it;
  anything unreadable means folded.)
- **Printers have the same notes.** A printer's page has the same **Notes** section, between its
  details and its 3MF files — for nozzle and bed, calibration, maintenance, quirks, where it lives.
  It is the very same component and the very same server rules as a model's, so everything above
  holds for it: Save/Discard and Ctrl/⌘ + S, the kept draft and the close-tab warning, the
  *someone else saved meanwhile* protection, the 20,000-character limit, and starting collapsed to
  the first two lines. A printer and a model can share an id number; their drafts and folded state
  are kept apart, and a printer's notes are never shown on a model's page or the other way round.
  Printers with notes get the same small note icon in the **Printers** list. Editing or
  decommissioning a printer leaves its notes alone. (Printer notes aren't searched: the search box
  is for models.)
- **Models with notes are marked** in the Models list (a small note icon; hover for the start of
  them), and **notes are searched** by the Models search box.
- Notes belong to the **model**, so they stay put when you upload a new version of the file. This
  is separate from the short note you can add to each file *version* when uploading, which
  describes that one file (and is where a scan records where a file was moved from).
- Technically they're new tables (`source_model_notes`, and `printer_notes` for printers), added to
  an existing database automatically on the next start. Nothing existing is altered, so upgrading
  needs no migration. (Tested by building a database with the previous version and starting the new
  one on it.) The save rules — tidying, the length limit and the conflict check, including the
  guarantee that two people saving at the same instant can't both win — live in one place,
  `backend/app/notes.py`, shared by both kinds.

## Searching models

The **search box** at the top of **Models** narrows the list as you type. Press **/** anywhere on
the page to jump to it, and **Esc** to clear it (a second **Esc** leaves the box).

- **Every word must match** — in any order, upper or lower case, and not necessarily next to each
  other: `great white` finds *GreatWhiteShark*; `frog shark` finds nothing.
- **A word matches the model's own name first.** If not, it can match the name of one of its **3MF
  files**, a **printer** it's sliced for, the **slicer** (so `vt 1190`, `prusa` or `2.9.5` are
  useful searches too), or its **notes** (see below). A model found that way says why under its
  name — *Matched: printer VT 1190*, or *Matched: note “…keep supports off…”* — so a result is
  never a mystery.
- The matched text is highlighted, the count reads *2 of 3 models*, and the search works together
  with the sort order.
- Opening a result and coming back keeps your search; leaving the Models section starts afresh.

## Comparing 3MF versions

Every version row of a 3MF has its own **Compare** button. Tick any two versions and press
**Compare** in the bar at the bottom: **v1 against v2 of the same 3MF**, two versions of
different entries, or versions on different printers — any pair. The diff names exactly the
two versions it's showing, lists every setting with the differences highlighted (the
*Only show differences* box narrows it), and says how many differ.

- **Differences are highlighted.** A differing row has a tinted background and an amber bar down
  its edge, and identical rows fade back so the changes stand out. Both values sit in a chip in
  their column's colour (amber left, teal right) with the part that actually changed picked out —
  the `18` in `0.18`, the `_rear` in `aligned_rear`, one edited character inside a long start
  G-code. A setting only one file has says "not in this file". Each category shows "N of M
  differ", and **Previous / Next difference** step through the changes (wrapping round, scrolling
  each into view) from a header that stays visible as you scroll. *Only show differences* hides
  everything else.
- Values are compared **exactly**, in full. (Earlier the comparison looked only at the first 70
  characters of a long value, so a change further in — late in a start G-code or in the printer
  notes — was reported as no difference.)
- A version whose files were pruned ("params only") can still be compared: its settings are
  kept even when its 3MF and gcode are not.
- Compare is between two: ticking a third replaces the oldest pick.
- Deleting a version that's ticked removes it from the selection.
- The Compare buttons are on the version rows themselves, on the model page and the printer page.

## Scanning the STL folder

Copy STL, OBJ or STEP files onto the NAS from another computer, then press
**Scan STL folder** on the Models page. Farmhand looks through the STL folder
(including sub-folders) and lists what isn't in the library yet. Everything is
ticked to start with; untick what you don't want and press **Move … into the
library**.

- **Each file is moved into Farmhand's own folder layout**, filed exactly the way
  an upload is: `<STL folder>/<number>/v1/<file name>`. A new model is made for it,
  named after the file, with a preview (STL only) kept on local disk. It's a
  *move*, not a copy: the file is no longer where you left it, so there's only
  ever one copy. The dialog says so before you press the button.
- **Your folders are left exactly as they are** — even if moving a file empties
  one. Farmhand never removes a folder it didn't make. The version's note records
  where each file came from (*moved here from Animals/Frogs*), so you can still
  tell.
- **It's safe to interrupt, or for something to go wrong.** The move is an instant
  rename within the folder (or a checked copy, then delete, if the folder spans
  disks). If a file can't be moved — no permission to take it out of its
  folder, a read-only share, a failure saving its record — it **stays exactly
  where it was**, nothing is left half-done (no stray copy, no empty folder, no
  orphaned preview), and the failure is named. Files never end up in two places.
- **Skipped:** hidden folders, `@eaDir`, `#recycle` and similar housekeeping
  folders, unfinished uploads (`*.part`), and symlinks. A file already in the
  library never shows up again, so scanning twice is harmless.
- **Look for the "name already in library" tag.** It marks a file whose name
  matches an existing model — usually a duplicate you'll want to untick. Two
  files with the same name in different folders are kept as two models and
  never overwrite each other.
- Large imports go in batches of 10 with progress. If one file can't be moved
  (it vanished, its name is too long, …) the rest still are, and the failure is
  named. At most 500 files are listed per scan; move them and scan again for more.
- If the STL folder is on a share that isn't connected, the scan says so rather
  than reporting "no new files".
- **Deleting a model deletes its file**, as for any model in the library, and
  tidies away the `<number>/v1` folders Farmhand made for it — but still never the
  folders it was originally in.
- Files that an earlier version of Farmhand imported *in place* keep working where
  they are, and deleting them still never tidies the folders around them. Moving
  to a new storage location (**Move them now**) brings them into the layout.

## Network storage

Everything is done from **Storage** in the sidebar — nothing to set up on the
computer running Farmhand, no files to edit.

1. **Add network share…** Give it a name and **paste the NAS folder's full address
   into the one address box** — Farmhand works out the type, server, share and
   sub-folder from it, and shows you how it read it before you connect. Any of
   these work:
   ```
   //192.168.1.50/farmhand/Projects       SMB
   \\nas\farmhand\Projects                SMB, as copied from Windows Explorer
   smb://nas.local/farmhand               SMB
   192.168.1.50:/volume1/farmhand         NFS
   nfs://nas/volume1/farmhand             NFS
   ```
   Add a username and password below if it's an SMB share that needs them (they
   stay out of the address). Farmhand connects straight away and **only saves the
   share if that works** — if not, it says why (can't reach it, wrong password,
   no share by that name, …).
2. Under **STL files** and **3MF files**, press **Change…**, jump to the share,
   open the folder you want (or make one with **New folder**) and press
   **Use this folder**. The two are chosen separately, and must be different folders.
3. Files you already have stay where they are and keep working. The page shows
   how many are in a previous location and offers **Move them now** (copy → check
   the size → update → delete the original).

Farmhand remembers its shares and **re-mounts them after every restart**, and
checks every 30 seconds — so a NAS that was switched on a little after the
computer is picked up on its own. A share shows as *not connected*, with the
reason, until it is; **Reconnect** retries immediately. (A wrong password is the
one thing it won't keep retrying by itself, so it can't lock the NAS account.)

### What this needs, and what it costs

**Two permissions for the container.** Mounting a share from inside a container
needs the `SYS_ADMIN` capability, and SMB needs `DAC_READ_SEARCH` as well:
`mount.cifs` keeps just those two while it drops every other privilege, and stops
with *"Unable to apply new capability set"* if the container wasn't given both.
So `docker-compose.yml` gives the `api` service
`cap_add: [SYS_ADMIN, DAC_READ_SEARCH]` (plus `apparmor:unconfined`, which only
matters on hosts running AppArmor, like Ubuntu). That is a real widening of what
the container may do — acceptable for a trusted home/workshop server, worth
knowing before you put this anywhere shared. NFS needs only `SYS_ADMIN`. The
Storage page checks for these and says exactly which one is missing (and still
lets you add an NFS share if only the SMB one is). After changing `cap_add`, run
`docker compose up -d` so the container is recreated with them. If you'd rather
not grant them, you can mount the share on the host yourself and add a bind
mount for it under `/data/nas/<name>` in `docker-compose.yml`; the Storage page
will still let you pick folders on it.

**Your NAS's side:** the account needs write access to the share. Farmhand runs as
root inside its container, so an NFS export must allow it (often `no_root_squash`,
or allowing this machine's IP). If SMB won't connect, try a specific version
under *Advanced* (3.0 or 2.1 for older NAS).

**Your login is stored** in Farmhand's database, as is, so it can reconnect after
a restart. It's never shown again or sent back to the browser, but anyone who can
read the database can read it — use a NAS account that only has access to this
share.

### Settings endpoints

| Method | Path | |
|---|---|---|
| GET | `/settings/config` | The settings the server holds (look, display preferences) and where their copy is kept |
| PUT | `/settings/config` | Save settings (only the parts given); refreshes the network copy |
| GET | `/settings/config/location/inspect?path=` | Look at a folder before choosing it: usable? already holds settings? |
| PUT | `/settings/config/location` | Choose the network folder (`null` = none); `if_exists`: `ask` (default), `restore`, `overwrite` |
| POST | `/settings/config/save-now` | Write the copy again now |
| POST | `/settings/config/restore` | Load the settings file in the chosen folder |

### Safety checks

- A folder can only be chosen if it's actually on a connected share or in
  Farmhand's own storage. The empty folder a *disconnected* share is mounted
  over lives in the container's throwaway filesystem, and is refused.
- Chosen folders get a small `.farmhand-storage` marker. If a share drops and
  leaves an empty folder behind, the marker is missing and uploads are refused
  with a clear message instead of quietly filling the local disk.
- **Thumbnails always stay on local disk**, so browsing keeps working while the
  NAS is off. Downloads and new uploads of the big files need it online.
- Deleting only ever removes the exact files Farmhand recorded — never a folder.

### What has been verified

Mounting has been confirmed on a real NAS: SMB and NFS shares connect from the Storage page, and
they come back by themselves after `docker compose restart`. Not exercised on real hardware yet:
a share dropping and coming back while Farmhand keeps running, and **Move them now** over a slow
network. Both are covered against a stand-in `mount` and NAS. If a connection fails, the message
on the Storage page is the real output of `mount`, translated.
