# Farmhand

Cataloging and versioning for a 3D print farm: every STL model and every 3MF sliced from it, version by
version, per printer, plus the printers themselves (Klipper/Moonraker and Prusa/PrusaLink): their print
history, maintenance, energy use, their cameras on one screen, and sending them a G-code to print.

Farmhand runs on one computer on your network (a Raspberry Pi, a mini PC, a NAS that runs Docker…) and is used
from a web browser on any computer, tablet or phone on the same network.

## Installing

### What you need

- **A Linux computer that stays on**, on the same network as your printers. A Raspberry Pi 4 or 5 (64-bit
  Raspberry Pi OS), or any PC running Ubuntu or Debian, is plenty.
- **Docker** with its **Compose** plugin, and **git**. Step 1 installs them if you don't have them.
- **Free network ports** on that computer: **3636** (the web page), **4545** (the server the page talks to) and
  **2727** (the database, only for looking at it yourself). The browser has to be able to reach the first two.

Farmhand is made of four parts, each in its own Docker container, which are always started together:

| Container | What it does |
|---|---|
| `web` | The web page, on port 3636 |
| `api` | The server: the archive, the printers, the files, the settings. Port 4545 |
| `db` | The database (PostgreSQL) everything is kept in |
| `go2rtc` | The video relay for cameras that only stream over RTSP (a Prusa's Buddy3D). Opens no ports of its own |

### 1. Install Docker and git

Skip this if `sudo docker compose version` and `git --version` already answer. Otherwise, Docker's own install
script sets up Docker and the Compose plugin on Raspberry Pi OS, Ubuntu and Debian:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
```

```bash
sudo sh get-docker.sh
```

```bash
sudo apt-get install -y git
```

### 2. Download Farmhand

Pick where it should live (here, `/opt/farmhand`) and download it there:

```bash
sudo git clone https://github.com/The-Original-Reth/farmhand.git /opt/farmhand
```

```bash
cd /opt/farmhand
```

If the repository is private, git asks for a username and password: give your GitHub username, and a
**personal access token** (GitHub › Settings › Developer settings › Personal access tokens) as the password.
To have it remembered for later updates (it's saved as plain text on that computer), run this once first:

```bash
sudo git config --global credential.helper store
```

### 3. Start it

In the Farmhand folder:

```bash
sudo docker compose up -d --build
```

The first time takes a few minutes (longer on a Raspberry Pi) while everything is built. Then check that all
four containers say **running**:

```bash
sudo docker compose ps
```

The containers start again by themselves after a power cut or a restart.

### 4. Open it

In a browser on any computer on your network, go to **http://&lt;the computer's IP&gt;:3636**, for example
`http://192.168.10.125:3636`. (On the computer itself, `http://localhost:3636` works too.) To find its IP:

```bash
hostname -I
```

A brand-new Farmhand is empty. Go on with the setup below.

## Setting it up

The first things to do, in this order. Everything is done in the web page; there are no files to edit.

1. **Settings** (left-hand menu, called Storage before). Where STL and 3MF files are kept. Out of the box they go in Farmhand's own
   storage on the computer it runs on. To keep them on a NAS instead, **Add network share…**, then choose the
   **STL files** and **3MF files** folders on it (see "Network storage").
2. **Settings location**, on the same page. Choose a folder on the NAS: Farmhand keeps a copy of its settings
   and of every printer's and model's records there, so a lost or rebuilt computer can be brought back with
   **Restore** (see "Where settings and records are kept").
3. **Printers › Add printer**, for each printer: its name, its IP, and how Farmhand reaches it:
   - **Mainsail (Moonraker / Klipper)**: usually just the IP. If Moonraker refuses Farmhand, either give its API
     key, or add Farmhand's computer to `[authorization] trusted_clients` in the printer's `moonraker.conf`.
   - **PrusaLink (Prusa Core One, MK4, XL…)**: the IP, and the PrusaLink password shown on the printer
     (Settings › Network › PrusaLink). The username is usually `maker`. A Buddy3D camera's IP goes here too
     (see "Monitor").
   A 3MF upload can also add the printer it was sliced for.
4. **Scan network** (beside Add printer) finds Klipper and Kalico printers, and Prusas running PrusaLink, in a range such
    as `192.168.1.0/24` and adds the ones you tick, named after their hostnames. The range starts as the network
    Farmhand's server is on (in Docker, which can't see the server's own network, the one most of your printers are
    on); change it to scan another. A Prusa that wants its PrusaLink password
    (as a Core One does) doesn't say its name, so it's listed by its IP, marked "needs password": add the password on its
    page afterwards. Each shows whether it answered over a cable or Wi-Fi (judged by its
    interface's name, such as `eth0` or `wlan0`). A printer on both is listed once, at its wired IP, and is added with
    both IPs. Rename them afterwards to match your slicer's printer profiles. A decommissioned printer found again is
    listed under its own name, and ticking it brings it back, with its history and 3MF files, instead of adding a copy. Only your own network can be scanned
    (a range starting 10., 172.16 to 172.31, or 192.168.).
5. **Models**: upload STL models and 3MF files, or copy them onto the NAS and use **Scan STL folder**.
6. **Monitor**: every printer's camera on one screen. Klipper printers' cameras appear by themselves, as set up
   in Mainsail.

## Updating

When there's a new version, run this in the Farmhand folder:

```bash
sudo sh update.sh
```

It downloads the newest version, then rebuilds and starts **all** the containers together
(`docker compose up -d --build --remove-orphans`), so a part added in a new version is never left out, and lists
them at the end: all four should say **running**. Your data is kept. Then reload Farmhand in the browser.

(A Farmhand downloaded before `update.sh` existed needs `sudo git pull` once first.)

## Backups and moving to another computer

- Everything Farmhand knows is in two Docker volumes on its computer: the database (`db_data`) and its own file
  storage (`storage_data`). Files kept on a NAS are on the NAS.
- With a **Settings location** chosen (see "Setting it up"), the settings, the network shares (without their
  passwords) and every printer's and model's records are also on the NAS, kept up to date after every change.
- **To move to a new computer, or after a lost one:** install Farmhand there (steps 1–4), add the same network
  share on the Settings page, choose the same settings folder, and pick **Use those settings**. Then type the
  share's and PrusaLink printers' passwords in again: they are never written to the NAS.

## Stopping and removing

In the Farmhand folder. To stop it (the data is kept, and `sudo docker compose up -d` starts it again):

```bash
sudo docker compose down
```

To remove it **and delete everything it holds** (the database and its own file storage; files on a NAS stay):

```bash
sudo docker compose down -v
```

## When something isn't working

- **See whether every part is running.** All four containers should say *running*:

  ```bash
  sudo docker compose ps
  ```

  If one is missing, `sudo sh update.sh` starts it. To see why one stopped, read its last messages (here, the
  camera relay's; use `api`, `web` or `db` for the others):

  ```bash
  sudo docker compose logs --tail 50 go2rtc
  ```

- **The page loads but stays empty, or says it can't reach the server:** the browser has to reach port 4545 on
  the same computer as well as 3636. Check a firewall isn't blocking it.
- **A printer says it can't be reached:** its IP, and that the computer running Farmhand can reach it. A Klipper
  printer that answers but refuses needs its Moonraker API key, or Farmhand added to `trusted_clients`.
- **A camera doesn't show on Monitor:** under the cameras, *No camera* lists the printers without one; point at
  a name to see why. Klipper cameras are played straight from the printer, so the *browser* has to be able to
  reach the printer. After changing a camera, press **Resync**.
- **A NAS share won't connect:** the Settings page shows the reason (see "Network storage").

## What's in it

**Models and 3MF files**
- Browsing STL folders and printers, and each 3MF's version history
- Uploading an STL/OBJ/STEP model, or a 3MF to an existing model or a new one. Dropping a 3MF reads its
  embedded printer profile: if that printer is registered it's used automatically; if not, you choose between
  creating it from the file (named exactly as the profile, so later uploads match) or picking an existing one
- **Version numbers in names.** A new 3MF version is saved as `Goldfish ver 1.3mf`, the next one as
  `Goldfish ver 2.3mf` (a "ver N" the uploaded name already ends with is replaced, not added to). Files
  uploaded before this keep their names.
- **Renaming** a model or a 3MF with the pencil beside its name. The extension can't change (an STL stays
  `.stl`, a 3MF stays `.3mf`); downloads use the new name. The stored file keeps its own name.
- **Stars.** A 3MF's first version has a silver star. Any later version can be starred gold — one per 3MF,
  clicking another moves it, clicking the gold one clears it.
- **G-code** (see "G-code" below): uploaded for a 3MF, shown under it, downloaded, or sent to the printer
- The 3MF settings viewer, laid out the way the slicer that made the 3MF shows its settings: PrusaSlicer BOSS
  edition's Print / Filament / Printer Settings tabs (pages down the left), or OrcaSlicer's (and Bambu Studio's)
  Process / Filament / Printer settings (pages across the top), each in that slicer's own colours (Prusa orange,
  Orca teal green), dark or light to match your colour scheme. Settings with no place on those pages are on an
  **Other** page, so none is hidden. And the compare/diff between any two versions
- Downloading a 3MF (greyed out once a version's files are pruned by the rolling window), its G-code, and a
  model's file
- **The Models list** is sortable by name, date added, number of 3MF files, number of printers, or type, in
  either direction. Names sort naturally (Part 2 before Part 10), and your choice is remembered.
- **Solid STL previews**, drawn from every triangle; **Redraw previews** on the Models page redraws them all
- **Scan STL folder** (see "Scanning the STL folder")
- **Notes** on every model, printer and 3MF (see "Notes")
- **Search**: the Models search box, and a search box on each printer's page for its 3MF files
- Deleting — always behind a confirmation that says exactly what will go:
  - a single 3MF version, or a whole 3MF with all its versions. Deleting a 3MF's last version removes the
    whole 3MF. Monument versions can be deleted too; the dialog warns first.
  - a single STL version (the folder stays, and can have a file added again), or a whole STL folder
    ("Delete folder"). 3MFs sliced *only* from that model are deleted with it (the dialog lists them);
    mixed-plate 3MFs that also use other models are kept, just unlinked from it.
  - Deleting removes the stored files (and their previews) and parsed settings for good.

**Printers** (see "Printers" below)
- Sortable by name, type, wired IP or wireless IP (remembered); add, edit and decommission. A decommissioned printer
  can be deleted (**Delete** on its page) once it has no 3MF files left; its print history, notes and maintenance go
  with it
- A **Mainsail** or **PrusaLink** button on each, opening the printer's own page in a new tab
- Each printer page: its details and notes, its 3MF files (with a search), its print history, and its
  Moonraker or PrusaLink section — each folds away, and all start folded
- **Moonraker (Klipper)**: connection, lifetime statistics, print history, energy, maintenance shared with
  Mainsail, and the 1500-hour service
- **PrusaLink (Prusa Core One, MK4, XL…)**: live status, sending a print, a print history Farmhand records,
  maintenance and the 1500-hour service

**Monitor** — every printer's camera on one screen: arranged by dragging, zoomable (see "Monitor")

**Power** — the whole farm's energy use (see "Power")

**Tools** — a list of websites you use around the farm, each opening in a new tab. **Add** puts a new one at the end
(an address without `https://` gets it added); each line has **Edit** and **Delete** at its end, and its handle on
the left drags it to another place. Each change is saved at once. The list is kept on the server
with the other settings, so every browser sees the same one. It starts out with Klipper guides and tools (the
Esoterical CANBus and USB guides, A better print_start macro, TMC Autotune, Shake&Tune, Klippy Detective,
energy usage monitoring, KIAUH, Moonraker Timelapse, and the Kalico, Klipper, KlipperScreen and Mainsail
documentation); change them like any other.

**Settings** — connecting a NAS (SMB or NFS) and choosing where STL and 3MF files go (see "Network storage"),
and where a copy of Farmhand's settings and records is kept

**Not wired into the UI yet** (the API supports these, nothing calls them):
- Monument flagging/unflagging (`PATCH /bundles/versions/{id}/monument`) — the UI shows monuments read-only.
- Deleting printers (retire one with "Decommissioned" instead — its history stays). Printers can be added
  from the Printers page or straight from a 3MF upload.

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
- Only the most recent versions keep their full files (the 3MF and G-code); older ones keep
  their parsed settings and preview — and anything flagged as a monument is kept in full.
- A new version is not a monument; the first one an entry ever had is.
- A 3MF version's name gets its version number: `Goldfish ver 2.3mf` (see "What's in it").

**What you see.** Versions run newest to oldest, top to bottom, whatever order the server
returns them in. Entries on a model page are grouped by printer, and under each printer the most
recently updated comes first; a printer's own page lists its entries newest first.

**Collapsing the versions.** Older versions start hidden: each entry shows its **most recent 3MF**, and a
**Show 3 older versions** / **Hide 3 older versions** button beside **New version** opens them. Clicking the
entry's header does the same. **Collapse all versions / Expand all versions** (beside *Upload 3MF*) does every
entry on the page at once, on both the model page and the printer page.
- Once you've opened or closed an entry that choice is **remembered in this browser** — across reloads, and
  between the model page and the printer page — even if the entry later gains versions.
- A version you've picked for compare stays picked while its entry is collapsed (the tray still
  lists it, and the entry keeps its highlight).

## G-code

- **Upload G-code** sits next to **Upload 3MF** (on the Models list and on a model's page). Pick the 3MF it was
  sliced from and drop in the `.gcode` or `.bgcode`: it goes with that 3MF's **newest version**, replacing a
  G-code that version already had. A G-code can also come with a 3MF when the 3MF is uploaded.
- It's named after its 3MF: `Goldfish ver 2.3mf` has `Goldfish ver 2.gcode`, whatever the slicer called it.
- Each version that has one shows it on a line under the version, with **Download** and **Send to
  &lt;printer&gt;** (the printer the 3MF was sliced for).
- **Sending** asks first (it starts printing straight away), then:
  - a **PrusaLink** printer gets the file on its USB drive and starts it; the print is added to its history
    at once
  - a **Klipper/Moonraker** printer gets it uploaded through Moonraker and started. A `.bgcode` (Prusa's binary
    G-code) is refused for it, saying to slice a plain `.gcode`.
  - A printer that's busy (printing, paused, waiting for someone) is refused and sent nothing.

## Printers

The **Printers** list sorts by **Name**, **Type**, **Wired IP** or **Wireless IP**: click a heading's arrow, and
again to reverse it (IPs sort as numbers; printers without that IP go last). The choice is remembered in this
browser. Its **Mainsail** or **PrusaLink** button opens the printer's own page in a new tab. A printer with notes
has a note icon, and one whose 1500-hour service is due says so. Each printer page has its details
and notes, then three sections that each fold away (all start folded): its **Moonraker** or **PrusaLink** section
(whose own parts, **Connection and statistics**, **Energy** and **Maintenance**, fold away too: they start open, and a
folded Maintenance still shows how many are due), its **3MF files** (with a search box — every word must match a file name, a model, the slicer or the
notes, or a printer profile), and its **print history**.

**Printer profiles.** In PrusaSlicer (and its BOSS edition) the Printers tab lists each physical printer with its
printer presets under it, for example a 0.4 and a 0.6 nozzle. Farmhand calls those presets the printer's **sub
printers**. Each 3MF says which one it was sliced with. When you upload one (a new 3MF or a new version), the
**Printer profile** box shows Farmhand's guess: the printer profile that preset's 3MFs went to before, else the one called
that, else a new one named after it. Change it to another of the printer's printer profiles, or **Create a new sub
printer…** with any name; Farmhand remembers the choice, so the next 3MF with that preset is guessed to go there
too (renaming a printer profile does the same for its old name). Each 3MF version shows its printer profile under its note. 3MFs uploaded before this are linked once when Farmhand starts.
On the printer page, **Printer profiles** lists them with how many 3MF files use each: click that count to show only
those 3MF files. **Add printer profile** adds one by hand, the pencil renames one (its 3MF files stay linked), the copy
button makes a new one with the same printer settings and parts, named "<its name> - copy" to start with (change it
before you press **Copy**; "- copy 2" and so on when that name's taken; its 3MF files and the default stay with the
original). The copy's **Printer Settings** show the original's, as its newest 3MF had them, "copied from" it, until a 3MF
sliced with the copy itself is uploaded; changing or removing the original later leaves the copy's as they were. The
bin removes one (its 3MF files stay, with no printer profile). The star makes one the printer's **default** (marked "default"
in orange; click the star again for none): every 3MF uploaded to that printer then starts on it instead of Farmhand's
guess, and can still be changed on the upload. They're kept in the settings copy on the NAS too.

Click a printer profile's **name** to open its **Printer Settings**, laid out like PrusaSlicer BOSS edition's Printer
Settings tab (General, Custom G-code, Machine limits, Extruder 1…, Notes, Dependencies). They're read from the newest
3MF sliced with it, or another picked under **Settings from**, and can't be changed here. The last page, **Printer
parts**, is Farmhand's own: write down the parts fitted to that printer profile (the part, its make, its model, when it was
installed, a note). Every part on the page can be typed into at once: change any of them, add others with **Add
part**, remove some with the bin, then **Save**, next to Add part, to keep the whole list in one go (nothing is
kept until then, and a part added and left empty is dropped). Close the window with changes not saved and Farmhand
asks whether to **Save** them, close and lose them (**Don't save**), or **Keep editing**. Every new printer profile starts
with **Toolhead, Hotend, Nozzle, Extruder, Gantry** and **XY motor** listed, ready to fill in. The default parts'
names can't be changed (their make, model, date and note can, and they can be removed); a part you added can be
renamed.

Each part has an **Add to name** tick box (all the default parts but the XY motor start ticked). The ticked parts'
models make a name: the printer's name without spaces, then each model in list order, with spaces turned into
underscores, for example `VT1190_Stealthburner_Rapido_UHF_0.5_WC_Galileo_2`. A part with no model yet is left out,
and the Gantry is only added when its make or model says AWD, 4WD or quad. The page shows the name as it stands. When
you close the Printer Settings window after saving changes to its parts, Farmhand asks whether to rename the printer profile to
it (only if it's different). Rename the preset in PrusaSlicer to match, or 3MFs sliced with the old name will add a
printer profile by the old name again. Parts are kept in the settings copy on the NAS as well.

**Connection.** In **Add printer** or **Edit**, choose **Mainsail (Moonraker / Klipper)** or **PrusaLink
(Prusa Core One, MK4, XL…)**. A printer on both a cable and Wi-Fi answers at both its IPs: give its **Wired IP**
and **Wireless IP** and leave the address below blank, and everything Farmhand does with it goes over the cable, and
over Wi-Fi only when the wired IP can't be reached: its status, prints, history and maintenance, its cameras on
**Monitor** (and in Mainsail, a camera written out with the printer's wired IP is moved to its Wi-Fi one too), and its
**Mainsail** / **PrusaLink** button. Farmhand remembers which IP answered, so a dead one isn't waited on each time, and
after two minutes on Wi-Fi it tries the cable first again, so it's back on the cable soon after it's plugged back in.
It only switches when a request never got through: one the printer took and then went quiet on is never sent twice,
so a print can't start twice. An address typed in is the only one used. (A Prusa's Buddy3D camera has one IP of its
own, so it has nothing to switch to.)
- Moonraker: the address defaults to port 7125 of the printer's IP; an API key is only needed if Moonraker asks
  for one.
- PrusaLink: the address defaults to the printer's IP. The username is usually `maker`, and the password is shown on the printer (Settings › Network › PrusaLink). A **Buddy3D camera IP** can be given too (see "Monitor").
API keys and passwords are stored as-is (they're needed for every call) but never sent back to the browser or
written to the copy on the NAS.

### Moonraker (Klipper) printers

- **Connection and statistics:** whether Klipper is ready, the printer's lifetime totals, and **Open
  Mainsail**. **Sync now** copies the latest print history; Farmhand also syncs every printer by itself every
  15 minutes, so nobody has to open its page.
- **The print running now:** while the printer is printing or paused, its file, a progress bar, the time
  printed and the time left, as Mainsail shows them (progress through the file; time left estimated from it). The
  page looks every 10 seconds while it's open, and syncs the history when a print starts or ends.
- **Print history:** Farmhand's own copy (kept even if the printer forgets it), searchable and filterable by
  completed / failed / cancelled, with each print's energy if the printer has a power meter.
- **Energy:** from a Moonraker `[sensor]` with an energy value (e.g. a smart plug): the whole printer
  (idle included, from meter readings Farmhand takes) and each print's own energy, **by month or by year**.
- **Maintenance:** kept in Moonraker's own database in Mainsail's format, so Mainsail shows the same list.
  Reminders by print time, filament and/or days, once or repeating; **Done** closes one (a repeating one starts
  its next round).

### PrusaLink printers (Prusa Core One…)

- **Live status:** printing / idle / error, nozzle and bed temperatures, the running print's file, progress,
  time printed and time left. The page looks every 10 seconds while it's open.
- **Send a print:** a sliced `.bgcode`/`.gcode` from your computer, onto the printer's USB drive, started
  straight away (asked first; refused while the printer is busy). G-code kept with a 3MF can be sent the same
  way (see "G-code").
- **Print history:** PrusaLink keeps none, so Farmhand records each print while it runs — every minute in the
  background, and every few seconds while the page is open. A print that starts and ends between two looks is
  missed; one whose end wasn't seen is recorded as completed if it was last seen at 99 % or more, else as
  unknown. The printer's total print time is what Farmhand has recorded.
- **Maintenance:** kept in Farmhand (PrusaLink has nowhere to keep it), counted against the recorded print
  time. No filament reminders: PrusaLink doesn't report filament use.

### The 1500-hour service

Every printer has a service reminder kept in Farmhand: due once 1500 print hours have been added since the
count started (the first sync) or since it was last marked **Done**. It has its own notes, and can be turned off
for a printer.

## Monitor

**Monitor** (in the left-hand menu) shows every printer's camera on one screen.

- **Which cameras:** a Klipper printer's cameras are the ones set up in Mainsail (Settings › Webcams), played
  the way Mainsail plays them (MJPEG, WebRTC through go2rtc or camera-streamer, snapshots at the frame rate set
  there). A Prusa's **Buddy3D camera** is added by its IP (below). Printers without a camera are listed
  underneath; point at a name to see why.
- **Same-size tiles** that fill the window and resize with it. A camera of another shape sits in its tile with
  black bars. Click a camera to see it on its own, filling the window; click again (or **Esc**) to go back.
- **Arranging:** drag a camera onto another to move it there, then **Save layout**. The order is kept on the
  server, so every browser shows the same. **Discard** goes back to the saved order; leaving the page with an
  unsaved layout asks first.
- **Zoom:** scroll over a camera to zoom in toward the pointer, drag a zoomed camera to look around, and click
  the badge in its corner (e.g. *2.6× ✕*) to see the whole picture again. **Max zoom** (2× to 8×, beside Save
  layout) limits how far, for everyone. Zoom only enlarges the picture the camera sends, so it gets softer the
  further in you go.
- **Picture-in-picture:** the button in a camera's top left corner floats it in a small window that stays on top
  of every other window, for any kind of camera; its tile says so while it's out there. Click the button again,
  or close the small window, to bring it back. Chrome and Edge only (Firefox and Safari don't show the button).
- **Mainsail / PrusaLink:** the link in a camera's bottom right corner opens its printer's own web page in a new
  tab: Mainsail, or PrusaLink for a Prusa reached that way. The bottom left corner names the printer as it's named
  in Printers.
- **Resync** asks every printer for its cameras again and connects to each anew: for a frozen picture, or after
  changing a camera in Mainsail.
- **Board:** the top right corner names the computer a Klipper printer runs on, as the printer itself reports it:
  *Pi 4*, *CM4*, *Pi 5*... Point at it for the full model and its memory.
- **Fast start:** each printer's cameras show as soon as that printer answers, so one that's switched off doesn't
  hold up the rest. Your browser also remembers each printer's cameras from last time, so they start connecting the
  moment Monitor opens, and change only if a printer now has different ones.

### A Prusa's Buddy3D camera

The Buddy3D only streams over RTSP (`rtsp://<camera IP>/live`), which browsers can't play, so Farmhand passes it
through **go2rtc** (its fourth container), and the page reaches that through the web page's own address.
1. In the **Prusa app**, turn on local streaming for the camera (camera firmware 3.1.0 or newer).
2. In Farmhand, open the printer's **Edit** (its connection set to **PrusaLink**) and put the camera's IP in
   **Buddy3D camera IP**, e.g. `192.168.10.131`. A whole `rtsp://…` address works too, for another RTSP camera.
3. Open **Monitor** (or press **Resync**).

Anyone on your network can watch a Buddy3D's stream: the camera itself has no password on it. Farmhand's web
page only passes through its own camera streams, never the rest of go2rtc.

## Power

**Power** (in the sidebar, under Storage) is the whole farm's energy use: every printer's power meter and print
energy (the same figures as each printer's Energy section), added up.
- **By month / By year**, a row per month or year: a bar split by printer (each in its own colour; hover for
  each one's kWh), the farm's print energy and its total.
- **Look at any month or year:** click its row, or use the **‹ ›** arrows and the list at the top. The tiles and
  the **By printer** table follow it: the whole farm's use, print energy and number of prints, and for each
  printer its meter reading, its use, its share of the farm's, and its print energy.
- "≥" marks a period in which a meter's readings began part-way through. Printers with no figures say why
  (e.g. PrusaLink doesn't report energy). Retired printers aren't counted.

## Appearance and settings

**Appearance** is its own item in the left-hand menu, the last one, just below **Settings**. The **Settings
location** (where a copy of the settings is kept on the network) is on the Settings page itself,
since it's about where things are stored.

### Appearance

- **Colour scheme:** *Farmhand* (the default, with brighter, whiter text), *Classic grey* (the
  original softer greys), *High contrast* (pure white on black), *Midnight blue*, *Violet* and
  *Light* (dark text on a light background). Each card previews the scheme in its own colours.
- **Text brightness:** pulls all the text toward white (or, on Light, toward black) — from the
  scheme's own text at 0% to as bright as it goes at 100%.
- **Font:** Archivo, your system's font, Verdana, Arial, **Play**, or monospace. Play is bundled
  with the app (served by Farmhand itself, open-source OFL licence), so it needs no internet.
- **Text size:** Small, Default, Large or Extra large (up to 25% bigger).
- **3MF file name colour:** 3MF names are shown bold in a box; their colour is the scheme's own, a preset, or
  any colour you pick.
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

### Where settings and records are kept

Farmhand's settings are: the look of the site (above), display preferences (the Models sort
order), and your storage setup (the STL and 3MF folders and the network shares).

- **On the server, always.** They're kept in Farmhand's database, so every browser and device
  shows the same look and order — change it on one, it changes on all.
- **Plus a copy on the network folder you choose.** Under **Settings location**, press **Choose
  folder…**, jump to a share and pick (or make) a folder. Farmhand writes
  `farmhand-config.json` there straight away and **after every change**, so the settings
  survive a rebuild or a lost database.
- **Printers and models are copied there too:** a file per printer in `printers/` (its setup, notes, print
  history, energy readings, the 1500-hour service and Farmhand-kept maintenance) and a file per model in
  `models/` (its notes, and each of its 3MF files' notes and starred version). **Restore** brings back what's
  missing and never overwrites what's already there.
- **Passwords are never written to it** — not a share's, not a Moonraker API key, not a PrusaLink password. A
  restored share comes back saved but not connected and says it needs its password (use **Edit** on it); a
  restored PrusaLink printer needs its password typed in again.
- **A folder that already holds settings is never overwritten without asking.** Pointing at one
  asks: *Use those settings* (restore them), or *Replace with current settings*. Until you
  choose, nothing is changed. A damaged file can only be replaced.
- **Restore** (also offered as a button once a folder is chosen) loads the file back: the look,
  the display preferences, the STL/3MF folders (even if their share hasn't reconnected yet — uploads
  stay refused until it's really there), any shares not already present, and the printer and model records.
  It's safe to run twice.
- **If the share is down** the settings are still saved on the server, the page says the copy
  couldn't be updated and why, and nothing is written into the empty folder underneath. **Save a
  copy now** catches it up once the share is back.
- **Use the server only** stops the copying; nothing on the network is ever deleted.

The folder must be on a connected share or in Farmhand's own storage — the same rule as the file
folders. After a total loss: re-add the share, choose the same settings folder, and pick *Use
those settings*.

## Notes

Every **model**, **printer** and **3MF** has a **Notes** section, and so does each printer's **1500-hour
service** — for anything worth remembering: print settings that work, where a model came from, its licence,
a printer's nozzle and bed, what the service involves. It's plain text (up to 20,000 characters); what you
type is shown exactly as typed and never treated as HTML. A 3MF's notes belong to the 3MF, shared by all its
versions.

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
- **Notes start folded** to their **first line** (with a "…" when there's more); **Expand** (or clicking the
  line) opens the editor, **Collapse** folds it again. Each choice is remembered for that model, printer or
  3MF in that browser. Folding never loses anything: unsaved edits are kept, and a restored draft is flagged in
  the folded view so it can't be missed.
- Models and printers with notes have a small note icon in their lists. **Model and 3MF notes are searched**
  by the Models search box (a printer's 3MF search looks at 3MF notes too).
- A model's notes stay put when you upload a new version of its file. This is separate from the short note
  you can add to each file *version* when uploading, which describes that one file.
- Every kind of notes follows the same rules, kept in one place: `backend/app/notes.py` on the server and
  `frontend/src/notes/` in the page.

## Searching models

The **search box** at the top of **Models** narrows the list as you type. Press **/** anywhere on
the page to jump to it, and **Esc** to clear it (a second **Esc** leaves the box).

- **Every word must match** — in any order, upper or lower case, and not necessarily next to each
  other: `great white` finds *GreatWhiteShark*; `frog shark` finds nothing.
- **A word matches the model's own name first.** If not, it can match the name of one of its **3MF
  files**, a **printer** it's sliced for, the **slicer** (so `vt 1190`, `prusa` or `2.9.5` are
  useful searches too), or its **notes**. A model found that way says why under its name —
  *Matched: printer VT 1190*, or *Matched: note “…keep supports off…”* — so a result is
  never a mystery.
- The matched text is highlighted, the count reads *2 of 3 models*, and the search works together
  with the sort order.
- Opening a result and coming back keeps your search; leaving the Models section starts afresh.

## Comparing 3MF versions

Every version row of a 3MF has its own **Compare** button. Tick any two versions and press
**Compare** in the bar at the bottom: **v1 against v2 of the same 3MF**, two versions of
different entries, or versions on different printers — any pair. The diff names exactly the
two versions it's showing and says how many settings differ. It opens in one of two views:

- **Slicer view** (the default): the two files side by side, each laid out as its slicer shows its settings, the
  same as a version's **Settings** button, in that slicer's colours. When both came from the same kind of slicer, their tabs and
  pages turn together: choose **Infill** on either side and both show their Infill page. A setting that differs
  has a bar down its edge on both sides (amber left, teal right), and each page shows how many of its settings
  differ. *Only show differences* leaves just those settings and their pages. A PrusaSlicer file against an
  OrcaSlicer one can be compared too, but their pages don't line up, so each side turns on its own.
- **List**: every setting by name, as described below.

- **Differences are highlighted** (List). A differing row has a tinted background and an amber bar down
  its edge, and identical rows fade back so the changes stand out. Both values sit in a chip in
  their column's colour (amber left, teal right) with the part that actually changed picked out —
  the `18` in `0.18`, the `_rear` in `aligned_rear`, one edited character inside a long start
  G-code. A setting only one file has says "not in this file". Each category shows "N of M
  differ", and **Previous / Next difference** step through the changes (wrapping round, scrolling
  each into view) from a header that stays visible as you scroll. *Only show differences* hides
  everything else.
- Variable names are shown exactly as in the 3MF, underscores and all.
- Values are compared **exactly**, in full.
- A version whose files were pruned ("params only") can still be compared: its settings are
  kept even when its 3MF and G-code are not.
- Compare is between two: ticking a third replaces the oldest pick.
- Deleting a version that's ticked removes it from the selection.

## Scanning the STL folder

Copy STL, OBJ or STEP files onto the NAS from another computer, then press
**Scan STL folder** on the Models page. Farmhand looks through the STL folder
(including sub-folders) and lists what isn't in the library yet. Everything is
ticked to start with; untick what you don't want and press **Move … into the
library**.

- **Each file is moved into Farmhand's own folder layout**, filed exactly the way
  an upload is: `<STL folder>/<number>/v1/<file name>`. A new model is made for it,
  named after the file, with a preview (STL only) next to it. It's a
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
- **Deleting a model deletes its file** (and its preview), as for any model in the library, and
  tidies away the `<number>/v1` folders Farmhand made for it — but still never the
  folders it was originally in.
- Files that an earlier version of Farmhand imported *in place* keep working where
  they are, and deleting them still never tidies the folders around them. Moving
  to a new storage location (**Move them now**) brings them into the layout.

## Network storage

Everything is done from **Settings** in the sidebar — nothing to set up on the
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
   the size → update → delete the original). Each file's preview moves with it.

Farmhand remembers its shares and **re-mounts them after every restart**, and
checks every 30 seconds — so a NAS that was switched on a little after the
computer is picked up on its own. A share shows as *not connected*, with the
reason, until it is; **Reconnect** retries immediately. (A wrong password is the
one thing it won't keep retrying by itself, so it can't lock the NAS account.)

### Previews live next to their files

Every preview image is saved **next to its file**, so it's on the NAS with the file: `Frog.stl` has
`Frog.stl.png`, `Goldfish ver 2.3mf` has `Goldfish ver 2.3mf.png`. A preview is written when its file arrives
(upload, scan, Redraw previews), deleted with it, and moved with it when the folder changes. When old 3MF
versions are pruned, the preview next to the pruned 3MF goes with it.

Farmhand also keeps **its own copy of every preview on local disk** — that's what the page shows, so browsing
keeps working while the NAS is off — and falls back to the one next to the file if its own is missing (e.g.
after a rebuild). Files from before this get theirs copied next to them a minute after Farmhand starts, then
hourly (for shares that come back later). A folder that can't be written to just goes without; the upload
isn't affected.

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
Settings page checks for these and says exactly which one is missing (and still
lets you add an NFS share if only the SMB one is). After changing `cap_add`, run
`docker compose up -d` so the container is recreated with them. If you'd rather
not grant them, you can mount the share on the host yourself and add a bind
mount for it under `/data/nas/<name>` in `docker-compose.yml`; the Settings page
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
| POST | `/settings/config/restore` | Load the settings file (and printer and model records) in the chosen folder |

The full API, with every route, is described at **http://localhost:4545/docs**.

### Safety checks

- A folder can only be chosen if it's actually on a connected share or in
  Farmhand's own storage. The empty folder a *disconnected* share is mounted
  over lives in the container's throwaway filesystem, and is refused.
- Chosen folders get a small `.farmhand-storage` marker. If a share drops and
  leaves an empty folder behind, the marker is missing and uploads are refused
  with a clear message instead of quietly filling the local disk.
- Browsing keeps working while the NAS is off (previews are shown from Farmhand's own copy). Downloads, new
  uploads and sending G-code need it online.
- Deleting only ever removes the exact files Farmhand recorded — never a folder.

### What has been verified

Mounting has been confirmed on a real NAS: SMB and NFS shares connect from the Settings page, and
they come back by themselves after `docker compose restart`. Not exercised on real hardware yet:
a share dropping and coming back while Farmhand keeps running, and **Move them now** over a slow
network. Both are covered against a stand-in `mount` and NAS. If a connection fails, the message
on the Settings page is the real output of `mount`, translated.

## For developers

Backend (FastAPI/SQLAlchemy/PostgreSQL) in `backend/`, frontend (React/Vite) in `frontend/`.

### Running it on your own computer

```bash
docker compose up --build
```

- Frontend: **http://localhost:3636**
- API: **http://localhost:4545** (docs at `/docs`)
- Postgres: `localhost:2727` (user/pass/db all `farmhand`). Inside Docker the API reaches it at `db:5432`.
- go2rtc: no ports of its own; the browser reaches it through the frontend's `/go2rtc/` address.

### Sample data

A brand-new database is an empty archive. To try Farmhand on the farm data it was built against
(the sample STL/3MF files aren't in the repository — copy them into
`backend/seed_data/` first; that folder's README lists them):

```bash
docker compose exec api python -m app.seed
```

Then refresh the frontend — 2 printers, 3 STL source models (with real
auto-generated thumbnails), and 3 real 3MF bundles (including the
mixed-plate Frog case) should appear.

### Mockup mode (the real web UI on sample data)

```bash
cd frontend
npm run mock
```

Opens **http://localhost:3637**: the real web interface, running on a built-in sample farm (printers including
a Core One, models, 3MF files with versions and G-code, print history, energy, maintenance, notes). No backend,
database or Docker is needed, and changes to the code show up live. Changes you make in the page (notes, stars,
maintenance…) last until the mockup restarts; **Reset sample data** (in the sidebar) starts afresh. Things that
need real files or hardware (uploading, mounting a NAS) answer "not available in the mockup". The fake backend
lives in `frontend/mock/` and is never part of a build or the Docker image.

### Project layout

```
backend/     FastAPI + SQLAlchemy + the 3MF parser — see backend/README.md
frontend/    React + Vite, talks to the backend over HTTP
  src/       the app: one folder per area (models, bundles, printers, power, storage, notes, compare, …)
  mock/      the fake backend for mockup mode
docker-compose.yml   brings up all four containers together
update.sh            pulls the newest version and restarts every container
```

### Local dev without Docker

Backend: see `backend/README.md`'s non-Docker instructions (remember to
pass `--port 4545`).

Frontend:
```bash
cd frontend
npm install
VITE_API_BASE=http://localhost:4545 npm run dev
```
Vite's dev server also runs on 3636 (configured in `vite.config.js`). For working on the interface without a
backend at all, use mockup mode (above).

### Testing

- **Backend:** `cd backend` then `python -m pytest -q`. A handful of tests check Linux-only behaviour (POSIX
  file permissions, symlinks, real mounts); on Windows they're skipped, saying why, and they run in the API's
  Docker image (Linux). Printers are tested against stand-ins for Moonraker and PrusaLink
  (`tests/fake_moonraker.py`, `tests/fake_prusalink.py`).
- **Frontend:** `npm run build` builds it; `npm run check:themes` checks every colour scheme's contrast.
- **Real hardware:** NAS mounting (SMB and NFS), Moonraker history/maintenance, Mainsail cameras (MJPEG and
  WebRTC through go2rtc) and a Buddy3D camera through Farmhand's go2rtc have been used against real devices. The PrusaLink connection and sending G-code to a Klipper printer follow the printers' published APIs
  but haven't been tried against a real printer yet; if one fails, its message on the page is the printer's own
  answer, translated.
