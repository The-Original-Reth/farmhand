# Writing a Farmhand plugin

A plugin is a program of your own that adds something to a print farm's Farmhand: a live stream, a dashboard, a
notifier. Streaming to YouTube is itself a plugin, [FarmHand - YouTube Plugin](https://github.com/The-Original-Reth/farmhand-youtube-plugin), in a repository of its own, and so is streaming to Twitch, [farmhand-twitch-plugin](https://github.com/The-Original-Reth/farmhand-twitch-plugin): Farmhand has no
Stream page of its own any more. It runs in **its own Docker container**, with its own storage, written in any language. It never touches
Farmhand's database, files or other containers. It reads what it needs from Farmhand through the **plugin API**
described here, using a token the operator gave it, and only what the operator allowed. Prusa printers may also be
connected through a plugin instead of their PrusaLink: it reports their status, and starts the prints Farmhand sends
them. [`plugins/prusa-connect`](../plugins/prusa-connect/README.md) does that through the farm's Prusa Connect server.

**Start from the example:** [`plugins/hello`](../plugins/hello/README.md) is a small, working plugin (each printer and
its print's progress, updated live, in Farmhand's colours) with its Dockerfile, tests and instructions for making it
your own. It shows everything below in use: the manifest, the token and its refusals, events, a page that works inside
Farmhand, and settings kept in the plugin's own volume.

What's here (plugin API version 1): the manifest, adding a plugin on Farmhand's Plugins page, the token and
permissions, the endpoints (and the one a plugin may report a printer's status through), the health check, and your plugin's page shown inside Farmhand. Farmhand doesn't
start or stop your container: the operator runs it (on Farmhand's machine or another one on the farm's network) the
way your instructions say, and adds it to Farmhand by its address.

## How a plugin is added

1. The operator starts your container, on any machine Farmhand can reach (for example `http://192.168.10.215:8080`),
   or beside Farmhand's own containers on its Docker network (`http://<id>:<port>`).
2. On Farmhand's **Plugins** page they type that address. Farmhand asks it for `GET <address>/manifest`, checks it,
   and shows its name and the permissions it asks for in plain words. They can untick permissions, and choose whether
   Farmhand takes your token only from that address (on by default).
3. Once they say yes, Farmhand shows them your plugin's `FARMHAND_URL` and `FARMHAND_TOKEN`, once, as two
   `KEY=value` lines. They put those in the env file your docker-compose.yml names under `env_file:` (beside it,
   like `stream.env` or `hello.env`) and start your container again (`sudo docker compose up -d --force-recreate`).

The Plugins page's **Run a plugin in its own container** walks the operator through it for any plugin with a compose
file: a folder for it (`/opt/farmhand-<name>`), your `docker-compose.yml` in it, `sudo docker compose up -d --build`,
adding it at `http://<that machine>:<its port>`, the two lines in its env file, and starting it again. So ship a
`docker-compose.yml` that builds or pulls your image, publishes your port, names an env file with `required: false`
(it isn't there until the plugin is added), and keeps your data in a volume: [`plugins/hello`](../plugins/hello/docker-compose.yml)'s
is a short one to copy.

From then on Farmhand asks your health path every 30 seconds, shows your page in its menu, and the operator can switch
your plugin off (its token is refused and its page leaves the menu), give it a new token, or remove it.

## The manifest: `farmhand-plugin.json`

Put it in your image at `/farmhand-plugin.json`, and serve the same thing at `GET /manifest`.

```json
{
  "id": "stream",
  "name": "Stream",
  "version": "1.0.0",
  "farmhand_api": "1",
  "author": "Your name",
  "homepage": "https://example.com/farmhand-stream",
  "port": 8080,
  "page": { "menu": "Stream", "icon": "video", "path": "/" },
  "permissions": ["printers:read", "cameras:read", "prints:read"],
  "settings_page": "/settings",
  "health": "/health"
}
```

| Field | Required | What it is |
|---|---|---|
| `id` | yes | 1 to 40 lower-case letters, digits and dashes, not starting or ending with a dash. Unique on a Farmhand; it becomes the plugin's address, `/plugins/<id>/` |
| `name` | yes | What the operator sees, up to 80 characters |
| `version` | yes | Your plugin's version, like `1.0.0` (letters, digits, `.`, `+`, `-`) |
| `farmhand_api` | yes | The plugin API version you wrote it for: `"1"` (a string). A Farmhand that doesn't speak it won't install the plugin |
| `port` | yes | The port your container listens on. A plugin added from its manifest alone (beside Farmhand, in Docker) is taken to be at `http://<id>:<port>` |
| `author`, `homepage` | no | Shown to the operator |
| `page` | no | A page in Farmhand's menu: `menu` (its label, up to 40 characters), `icon` (optional: `youtube`, `video`, `camera`, `chart`, `bell`, `dashboard` or `twitch`; a puzzle piece otherwise), `path` on your plugin (default `/`). See "Your page inside Farmhand" |
| `permissions` | no | What it needs to read (below). Ask only for what you use: the operator sees each one in plain words before saying yes |
| `settings_page` | no | Your plugin's settings, shown on Farmhand's Settings page under your plugin's name (below Farmhand's own): a path on your plugin, like `/settings` or `/?view=settings`. See "Your settings on Farmhand's Settings page" |
| `health` | no | A path that answers 2xx while your plugin is well. Farmhand asks it every 30 seconds (`/manifest` when there's none) and shows the operator "running", "running, with a problem" (any other answer: send a short plain-words reason as text, like "Farmhand refused this plugin's token: make a new one on the Plugins page"; your page is still shown) or "not answering" (nothing answered: Farmhand shows that in place of your page). While it answers well, Farmhand also reads your `/manifest` again, so a new `name`, `version` or `page` shows without adding the plugin again; a manifest asking for a permission it didn't ask for before is not taken (the operator adds the plugin again to grant it) |
| `print` | no | A plugin Prusa printers are connected through, which starts the prints Farmhand sends them: `{"path": "/farmhand/print"}`, the path Farmhand POSTs each print to. Needs `printers:print` in `permissions`. See `PUT /printers/{id}/status` and "Starting the prints Farmhand sends" |
| `stream_control` | no | A stream plugin that Stream control starts and stops: `{"path": "/api/stream-control", "site": "YouTube"}` (`site`, up to 40 characters, is shown beside it), and optionally `"settings": "/?view=youtube-settings"`, a page of yours for that site's own settings, which Stream control opens in a window of its own from a "<site> settings" button. See "Stream control" |

Farmhand checks the manifest when the plugin is installed, and says in plain words what's wrong with one it won't take.

## Permissions

| Permission | What the operator is told it lets the plugin do | Endpoints |
|---|---|---|
| `printers:read` | see your printers: their names, how Farmhand reaches them and their addresses (never passwords or API keys) | `GET /printers` |
| `cameras:read` | see your printers' cameras and the addresses to stream them from | `GET /cameras` |
| `prints:read` | see what each printer is printing and how far along it is, and hear when a print starts, pauses or ends | `GET /printers/{id}/print`, `GET /events` |
| `farm:read` | see Farmhand's colours and the farm's time zone | `GET /farm` |
| `stream:migrate` | take, once, a copy of the Stream page set-up this Farmhand saved before Stream became a plugin: its settings and saved layouts, the stream key and the YouTube sign-in (Farmhand keeps its copy) | `GET /stream/migrate`, `POST /stream/migrate` |
| `stream:read` | see the stream designed in Stream control (its layout, words, pictures and music) to send it to its site | `GET /stream/design`, `GET /stream/pictures/{name}`, `GET /stream/slideshows/{show}/pictures/{name}`, `GET /stream/music/{name}` |
| `printers:report` | report what your Prusa printers are doing (their state, temperatures and prints), in place of Farmhand asking their PrusaLink, for the printers you connect through it | `PUT /printers/{id}/status` |
| `printers:print` | start the prints you send from Farmhand to the Prusa printers you connect through it (it is handed each G-code to send on) | `GET /prints/{ticket}/file`, and the manifest's `print` path |

The operator grants some or all of the permissions the manifest asks for, never more. `printers:report` and
`printers:print` are the only ones that change anything, and only for the printers the operator connects through the
plugin; others are added one at a time, when a plugin needs one.

`stream:migrate` is only for a Stream plugin taking over from the Stream page older Farmhands had built in (like
[FarmHand - YouTube Plugin](https://github.com/The-Original-Reth/farmhand-youtube-plugin)): ask for it only if that's what your plugin is. It hands over secrets
(the stream key, the Google client secret and the YouTube sign-in), so it's granted only when the manifest asks and the
operator leaves it ticked, and handed over just once.

## Reaching Farmhand

Your container is given two environment variables:

- `FARMHAND_URL`: where the plugin API is: Farmhand's API port as the farm's network reaches it, e.g.
  `http://192.168.10.213:4545/plugin-api/v1`, or `http://api:4545/plugin-api/v1` for a container on Farmhand's own
  Docker network
- `FARMHAND_TOKEN`: your plugin's token

Send the token with every call:

```
GET $FARMHAND_URL/printers
Authorization: Bearer $FARMHAND_TOKEN
```

- No token, or one Farmhand doesn't know, is **401** (with `WWW-Authenticate: Bearer`). A token stops working when
  the operator makes a new one for the plugin, removes the plugin, or turns it off: read `FARMHAND_TOKEN` again when
  your container restarts. An `/events` connection open at the time is ended within about 15 seconds (reconnecting
  then gets the 401).
- A call outside your plugin's permissions is **403**, naming the permission it needs.
- When the operator chose to take your token only from your plugin's address, a call from anywhere else is **403**,
  saying where it came from. Call Farmhand from the machine at the address you were added by (a container's calls
  come from its host's address, or from its own on Farmhand's Docker network).
- Asking more than 10 times a second (after a burst of 60) is **429**, with `Retry-After` in seconds.
- Every error is JSON, `{"detail": "..."}`, in words meant for the operator: show it as it is.

Answers are kept by Farmhand for a few seconds (printers 5 s, cameras 15 s, a print 3 s, the farm 10 s), so asking more
often than that gets the same answer. Ask for a print's progress every few seconds at most, and use `/events` rather
than asking every printer in a loop.

The plugin API is reached over the farm's network: see "Across the network" below.

## The endpoints

All under `/plugin-api/v1`. Every answer is a JSON object (so fields can be added later).

### `GET /me` (any valid token)

Which plugin the token is, and what it may read. A good first call, to check the token works.

```json
{ "plugin_id": "stream", "permissions": ["cameras:read", "printers:read", "prints:read"], "api_version": "1" }
```

### `GET /printers` (`printers:read`)

Every printer in service (retired ones are left out), by name. `connection_type` is `moonraker` (Klipper) or
`prusalink` (Prusa). `status_from` is the plugin (its id) a Prusa printer's status comes from, or `null` when Farmhand
asks the printer itself (see `PUT /printers/{id}/status`). Addresses that don't apply to the printer's kind are `null`.
Never an API key or password.

```json
{
  "printers": [
    {
      "id": 1, "name": "VT 1190", "kind": "Voron Trident", "connection_type": "moonraker", "status_from": null,
      "addresses": {
        "wired_ip": "10.0.6.21", "wireless_ip": "10.0.7.21",
        "moonraker_url": "http://10.0.6.21:7125", "mainsail_url": "http://10.0.6.21/",
        "prusalink_url": null, "camera_address": null
      }
    },
    {
      "id": 2, "name": "Core One", "kind": null, "connection_type": "prusalink", "status_from": "prusa-connect",
      "addresses": {
        "wired_ip": "10.0.6.30", "wireless_ip": null, "moonraker_url": null, "mainsail_url": null,
        "prusalink_url": "http://10.0.6.30", "camera_address": "10.0.6.40"
      }
    }
  ]
}
```

### `GET /cameras` (`cameras:read`)

Every printer in service with its cameras, as set up in Mainsail (or a Prusa's Buddy3D camera), each with an address
ffmpeg can read: `kind` is `mjpeg` or `rtsp`, `url` the address, and `ffmpeg_input` the options to read it with
(reconnecting, timeouts; the Stream plugin uses them as they are), ending in `-i <url>`. Farmhand runs no ffmpeg itself. `rotation` and the flips are as set in Mainsail;
`ffmpeg_filters` turns the picture that way (add them to your filter graph). A camera that can't be streamed (one
that only plays in a browser, over WebRTC) has `kind`, `url` and `ffmpeg_input` `null` and says why in `error`. A
printer whose cameras couldn't be asked (it's off) has no cameras and says why in its own `error`.

```json
{
  "printers": [
    {
      "printer_id": 1, "printer_name": "VT 1190", "error": null,
      "cameras": [
        {
          "name": "Bed", "kind": "mjpeg", "url": "http://10.0.6.21/webcam/?action=stream",
          "ffmpeg_input": ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1",
                           "-reconnect_delay_max", "5", "-rw_timeout", "10000000", "-use_wallclock_as_timestamps", "1",
                           "-f", "mpjpeg", "-i", "http://10.0.6.21/webcam/?action=stream"],
          "rotation": 90, "flip_horizontal": true, "flip_vertical": false, "ffmpeg_filters": ["transpose=1", "hflip"],
          "aspect_ratio": "4:3", "target_fps": 15, "snapshot_url": "http://10.0.6.21/webcam/?action=snapshot",
          "error": null
        },
        {
          "name": "Nozzle", "kind": null, "url": null, "ffmpeg_input": null,
          "rotation": 0, "flip_horizontal": false, "flip_vertical": false, "ffmpeg_filters": [],
          "aspect_ratio": "16:9", "target_fps": 15, "snapshot_url": null,
          "error": "VT 1190's Nozzle camera only plays in a browser (WebRTC), which Farmhand can't send to a stream. In Mainsail (Settings → Webcams) give it the MJPEG streamer service, or leave it out of the stream."
        }
      ]
    },
    {
      "printer_id": 3, "printer_name": "MK4 Shelf", "cameras": [],
      "error": "Moonraker at http://10.0.6.40:7125 didn't answer in time. Is the printer on?"
    }
  ]
}
```

### `GET /printers/{id}/print` (`prints:read`)

The print under way on one printer, as Mainsail or PrusaLink shows it. `state` is `printing`, `paused`, or `null`
(nothing under way); `progress` is 0 to 100, through the file; `error` says why the printer couldn't be asked (the
other fields are then `null`). **404** for a printer that doesn't exist.

```json
{ "state": "printing", "progress": 42.4, "file": "Frog.gcode", "error": null }
```

### `GET /events` (`prints:read`)

[Server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html): a connection that stays open,
with an event each time something changes. Farmhand works these out from what it already sees of its printers: it
looks at every printer once a minute while a plugin listens (and whenever the Monitor page asks), so an event comes
up to a minute after the change. The first look at a printer only notes how it is; events are changes after that.

| Event | When |
|---|---|
| `print.started` | a print is under way that wasn't (or a different file is) |
| `print.paused` | the print was paused (also right after `print.started` for one first seen paused) |
| `print.resumed` | the paused print carries on |
| `print.finished` | the print is no longer under way: it completed, or was cancelled. Ask the printer which, if it matters |
| `printer.unreachable` | the printer couldn't be asked (`error` says why). Not taken as its print ending |
| `printer.reachable` | it answers again |

Each event's `data` is one line of JSON:

```
id: 7
event: print.started
data: {"id":7,"type":"print.started","at":"2026-11-11T14:02:11.120000+00:00","printer_id":1,"printer_name":"VT 1190","file":"Frog.gcode","progress":0.3}
```

`print.*` events carry `file` and `progress` (`progress` is `null` on `print.finished`); `printer.*` events carry
`error` (`null` on `printer.reachable`). The stream opens with a comment line (`: connected`), and another
(`: still here`) comes every 15 seconds while nothing happens, so you can tell the connection is alive: one silent for
much longer than that has gone (time your reads out at 45 seconds or so). Events aren't kept: one that happens while
you're not connected is missed, so after connecting, ask `GET /printers/{id}/print` for how things stand. Reconnect if
the connection drops (Farmhand restarting ends it). Events say when a print starts, pauses or ends, not how it creeps
along: for progress, ask each printer's print now and then (every 20 seconds or so is plenty).

### `PUT /printers/{id}/status` (`printers:report`)

A Prusa printer's status, from the plugin it's connected through. The operator chooses that for each Prusa printer
under **Connection** when adding or editing it, where each such plugin is a choice beside Mainsail and PrusaLink;
`GET /printers` says which, in `status_from`. Any other printer is refused with 403, saying how it's connected now.

Farmhand then answers from your reports wherever it would have asked the printer's PrusaLink: the printer's page,
Monitor, `GET /printers/{id}/print`, `/events`, and the print history it records (a new `job.id` is a new print; a job
that reaches `FINISHED`, `STOPPED` or `ERROR` has ended). Farmhand doesn't contact the printer's PrusaLink at all: a
print sent to it goes to your plugin (`printers:print`, below), or isn't sent.
Report every few seconds, also while nothing changes: a printer with no report for two minutes shows as unreachable,
saying your plugin hasn't reported.

In PrusaLink's own words (states `IDLE`, `BUSY`, `PRINTING`, `PAUSED`, `FINISHED`, `STOPPED`, `ERROR`, `ATTENTION`,
`READY`); every field may be left out or `null`:

```json
{
  "reachable": true, "error": null,
  "state": "PRINTING",
  "temps": { "temp_nozzle": 214.6, "target_nozzle": 215, "temp_bed": 60, "target_bed": 60 },
  "printer_type": "COREONE", "firmware": "6.4.0",
  "job": {
    "id": 12, "state": "PRINTING", "file": "Frog keychain.bgcode", "path": "/usb/FROGKE~1.BGC",
    "progress": 40, "time_printing": 1200, "time_remaining": 1800
  },
  "link": "http://192.168.10.93:8080/printers/0199a1b2-…",
  "extras": {
    "material": "PETG", "nozzle_diameter": 0.4, "nozzle_hardened": false, "nozzle_high_flow": false,
    "temp_chamber": 29.4, "target_chamber": 0, "print_fan_rpm": 0, "heatbreak_fan_rpm": 8003,
    "speed": 100, "flow": 100, "odometer_e": 236033,
    "dialog": { "code": "13501", "title": "Filament runout", "text": "Insert filament, then press Retry." }
  }
}
```

`extras` is what you know beyond PrusaLink; every field may be left out. Farmhand shows them on the printer's page
(`dialog` is a message on the printer's screen, `null` when there's none). `odometer_e` is the mm of filament the
extruder has ever fed: for a print Farmhand sees start (within five minutes of it), it measures the print's filament as
the odometer at the end less at the start, instead of estimating it from the slicer, and weighs it from the
`material` loaded when neither its G-code nor its 3MF gives a density. The odometer is also the printer's lifetime
filament (its "Filament used"), which filament maintenance reminders count. Prints recorded before keep their figures.

`reachable: false` with an `error` in plain words says you can't hear from the printer now; Farmhand shows the error as
the printer's. `link` is where the operator can see it (an "Open in <your plugin>" button on its page). `job.id` is a
whole number (the printer's own job number); `progress` 0 to 100; times in seconds. The answer is
`{"recorded": true, "error": null}`, or `recorded: false` with why.

### Starting the prints Farmhand sends (`printers:print`)

With `printers:print` and a `print` path in your manifest, a print the operator sends to a printer connected through
your plugin is handed to you. Farmhand first checks the printer is ready from your latest report (else it says it's
busy), then POSTs to `<your address><print path>`, and waits (up to ten minutes) for your answer:

```json
{ "ticket": "l3H0q…", "printer_id": 2, "file": "Frog keychain.bgcode", "size": 1048576 }
```

Fetch the G-code with `GET /plugin-api/v1/prints/{ticket}/file` and your token (it streams the bytes;
`X-Farmhand-File` is the file's name, URL-encoded). A ticket works once, only for your plugin, and only while Farmhand
is waiting for your answer, so a POST that didn't come from Farmhand fetches nothing. Then start the print and answer
`200 {"sent": "usb/Frog keychain.bgcode"}`, where it went on the printer. To refuse, answer `409 {"detail": "…"}` when
the printer isn't ready, or any other error status with a `detail` in plain words; Farmhand shows it to the operator.

### `GET /farm` (`farm:read`)

Farmhand's colours, as its pages show them now (the scheme and text brightness chosen on the Appearance page), so your
page can match, and the farm's time zone (an IANA name, or `null` when no browser has said yet). `mode` is `dark` or
`light`. The colours' names are Farmhand's own: `amber` is the accent colour (buttons, selection) and `teal` the
second one, whatever their hue in the scheme.

```json
{
  "scheme": "farmhand", "mode": "dark", "time_zone": "America/New_York",
  "colors": {
    "bg": "#1B1D1E", "panel": "#232527", "panelAlt": "#2A2C2E", "panelHover": "#303335",
    "border": "#3D4042", "borderStrong": "#565A5D",
    "textPrimary": "#F4F5F4", "textMuted": "#CBCED0", "textFaint": "#A3A7AA", "heading": "#FFFFFF",
    "amber": "#E39F3A", "amberDim": "#4A3A20", "amberBorder": "#6B5428",
    "teal": "#69A0A6", "tealDim": "#1F2E30", "tealBorder": "#2C4548",
    "fileName": "#6AAEF5", "projectOnly": "#B394FF",
    "green": "#6FBE7A", "greenDim": "#233A26", "greenBorder": "#345F3C",
    "danger": "#E27A72", "dangerDim": "#3A2321",
    "onAccent": "#241A08", "onTeal": "#0B2224", "onDanger": "#1B0A09"
  }
}
```

### `GET /stream/migrate` and `POST /stream/migrate` (`stream:migrate`)

For moving a Farmhand that had its own Stream page (before Stream became a plugin) onto the Stream plugin: what that page
had set up, handed to the plugin **once**, so the operator doesn't set it all up again. Farmhand no longer has that
page, but what it saved is still in Farmhand's database. Farmhand only reads it (it keeps it; it isn't changed or deleted), and records that it was handed over: a second `POST` is
**410**, saying when. Removing the plugin on the Plugins page and adding it afresh lets it ask again.

`GET` says whether it can still be handed over, with nothing secret in it:

```json
{ "available": true, "handed_over_at": null, "has_settings": true }
```

`POST` hands it over. `settings` is the Stream page's settings exactly as Farmhand kept them (its grid and squares,
taking turns, resolution, colours, font, music, delay, YouTube title, description and settings: the Stream plugin's
`streamer/live_stream/choices.py` reads the same shape), `layouts` its saved layouts as stored, `stream_key` the pasted
key (or `null`), `youtube` the Google OAuth client and sign-in (each `null` when there's none), and `stream_folder` the
stream folder that page had chosen (its pictures, slideshows and music, for the operator to give your container the
same folder), or `null` when it used the default. A Farmhand that never had the page answers `{}`, `[]` and `null`s:

```json
{
  "settings": { "cols": 2, "rows": 1, "cells": [{ "camera": "1:Bed" }, null], "title": "The farm", "resolution": "1080p" },
  "layouts": [{ "name": "Morning", "cols": 1, "rows": 1, "cells": [{ "camera": "1:Bed" }], "layout": "grid" }],
  "stream_key": "abcd-efgh-ijkl-mnop",
  "youtube": {
    "client": { "client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-..." },
    "refresh_token": "1//0g...", "channel": "Print Farm", "stream_id": "abc123"
  },
  "stream_folder": "/data/nas/farmhand/stream",
  "handed_over_at": "2026-11-11T10:00:00+00:00"
}
```

Keep what you're handed as carefully as Farmhand did: never show it on your page or answer it from your API.

## Stream control

**Stream control** is a plugin built into Farmhand (switched on or off on its Plugins page): the operator designs one
stream there, and every stream plugin sends that one stream to its own site. A stream plugin takes part in two ways.

**It reads the design** (`stream:read`). `GET /stream/design` answers `{"enabled": false}` while Stream control is
switched off, or while the operator has left your plugin out of it (send your own layout, as before), or:

```json
{
  "enabled": true,
  "design": {
    "cols": 2, "rows": 1,
    "cells": [{ "camera": "3:Nozzle" }, { "background": "#1F3A5F", "image": "logo.png", "slideshow": null, "text": "Live", "...": "..." }],
    "cameras": ["3:Nozzle"], "show_status": true, "layout": "grid", "seconds_all": 30, "seconds_each": 20,
    "resolution": "720p", "border_color": "#000000", "background": "#000000", "font": "play", "color": "#FFFFFF",
    "music": true, "music_volume": 50, "music_shuffle": true, "music_from": ["stream-control"], "delay": 60,
    "holding": { "text": "Back in a minute", "image": null, "background": null, "color": null, "font": null },
    "title": "The print farm, live", "description": "", "revision": 7, "saved_at": "2026-11-17T18:00:00Z"
  },
  "media": { "images": ["logo.png"], "slideshows": [{ "name": "Finished prints", "images": ["frog.jpg", "blank:1"] }], "music": ["beat.mp3"], "error": null,
             "stamps": { "images/logo.png": "4113-1794970738232660700" } }
}
```

The design is in the same shape as the YouTube and Twitch plugins' own stream settings (their `live_stream`
settings and squares), so one of them can use it in place of its own. Cameras are `"printer id:camera name"`, as
`GET /cameras` names them. Besides `camera`, a square has `background`, `image`, `slideshow`, `seconds`, `text`,
`color`, `font`, `band`, `picture_box`, `text_box`, `captions`, `picture_boxes`, `layers` and `slide_layers`, as the
plugins' own squares do. `music_from` is where the music comes from: `"stream-control"` (Stream control's own music
folder) and/or stream plugins' ids (their tracks, passed on). A slideshow's `"blank:N"` is a blank screen, not a file. `revision` goes up by one each time
the operator saves: ask every few seconds, and change the stream when it has. `media.stamps` gives each file's stamp (`{"images/logo.png": "<size>-<modified>", ...}`): fetch only the files that
are new or whose stamp changed, not all of them each time. (Farmhand reads the folder again when the design is saved, a file is added or taken out through it, or Scan folder is pressed: a file replaced there by hand gets its new stamp then.) Fetch the files it names from
`GET /stream/pictures/{name}`, `GET /stream/slideshows/{show}/pictures/{name}` and `GET /stream/music/{name}` (404
while Stream control is off or when the file has gone). What only your site has (its stream key, sign-in, privacy or
category) stays in your plugin.

**Stream control's layout takes over.** While `GET /stream/design` answers `enabled: true` (Stream control is on and
the operator has ticked your plugin under its Streams), send that design, not your own layout: keep your own saved
(don't change or delete it), and go back to it as soon as the answer is `{"enabled": false}` (switched off, or your
plugin unticked). While it's taken over, your page shows **"Controlled by Stream control"** where your layout editor
is, in place of the editor (with a link or a word that the layout is changed in Farmhand's Stream control), and your
`stream_control` status answers `"following": true`. What only your site has (stream key, sign-in, privacy,
category) stays editable on your page.

**Farmhand starts and stops it.** Put `stream_control` in your manifest with the path Farmhand calls, where your plugin
runs:

- `GET <path>`: how your stream is doing, `{"live": true, "following": true, "error": null, "watch_url": "https://..."}`.
  `following`: you send Stream control's design (false: your own layout). `error`: why it isn't live when it should be,
  in plain words.
- `POST <path>/start` and `POST <path>/stop`: go live (with Stream control's design when it's on) or stop, answering the
  same. A start that can't happen answers 4xx with `{"detail": "why, in plain words"}` (no stream key yet, say): the
  operator sees it as it is.

Stream control lists every added plugin with `stream_control`, asks each switched-on one every few seconds, and calls
start and stop from its **Go live** and **Stop** buttons, **Go live everywhere**, **Stop all** and its schedule.

## Versions

- `/plugin-api/v1` stays as it is. It only ever **gains**: new endpoints, new fields in an answer, new event types,
  new permissions. Nothing is renamed, retyped or taken away. So ignore fields and event types you don't know.
- A change that would break a plugin is a new version, `/plugin-api/v2`, served beside v1 for a while so plugins
  can move over.
- `farmhand_api` in your manifest says which version you wrote for.

## Your page inside Farmhand

A plugin with a `page` gets an entry in Farmhand's menu (while it's switched on). Its page is shown in a frame under
Farmhand's top bar, from Farmhand's own address: the browser asks Farmhand's web server for `/plugins/<id>/<path>`, and
Farmhand passes that on to your plugin's `<address>/<path>`, with your answer passed back as it is (streamed, so
server-sent events work). So:

- Use **relative** addresses in your page (`api/status`, `style.css`, not `/api/status`): they then work both inside
  Farmhand and opened straight on your plugin. Each request carries `X-Forwarded-Prefix: /plugins/<id>` if you need
  to build an address; a redirect to one of your own addresses is pointed inside Farmhand for you.
- Websockets aren't passed on yet: use server-sent events, or ask every few seconds.
- Don't send `X-Frame-Options: DENY` or a `frame-ancestors` that leaves Farmhand out, or the page can't be shown.
- When your plugin isn't answering, Farmhand shows "This plugin isn't running" with what went wrong instead of your page.
- Your page shares Farmhand's address, so the operator is trusting your page as they trust Farmhand's: it may not
  move Farmhand's own page elsewhere, and it should only ever talk to your own plugin.

To match Farmhand's colours, load its small helper script:

```html
<script src="/plugins/farmhand-plugin.js"></script>
<style>
  body { background: var(--farmhand-bg); color: var(--farmhand-text-primary); font-family: var(--farmhand-font); }
  a, button.primary { color: var(--farmhand-amber); }
</style>
```

It sets a CSS variable on `<html>` for every colour of `GET /farm` (`--farmhand-bg`, `--farmhand-panel`,
`--farmhand-text-primary`, `--farmhand-amber`... in kebab-case), plus `--farmhand-font`, `data-farmhand-mode`
(`dark` or `light`) and `color-scheme`, and keeps them up to date when the operator changes Farmhand's look. In
script: `window.farmhand.theme` (`{mode, colors, font}`, or `null` until Farmhand sends it),
`window.farmhand.onTheme(fn)` (called now and on every change; returns a function that stops it),
`window.farmhand.inFarmhand`, and a `farmhand:theme` event on `document`.

### Your settings on Farmhand's Settings page

Farmhand's **Settings** page has Farmhand's own settings (where it saves its files) under a **Farmhand** heading, then a
heading for each plugin, its name, with that plugin's settings under it. Give your manifest a `settings_page` and
Farmhand shows that page of yours there, in a frame, the same way as your main page (from `/plugins/<id>/<path>`):
where your plugin saves things, and anything the operator sets. Without one, the operator is told your plugin has no
settings to show there (with a link to your page, if you have one).

The frame is as tall as your page: `farmhand-plugin.js` tells Farmhand your page's height whenever it changes, so load
it on that page too. Keep the page short and to the point: no page-wide background or padding of its own is needed,
as it sits inside Farmhand's own page. A plugin that's switched off or not answering shows that instead.

A settings page with things to save gets a **Save** button on its heading row, at the right of your plugin's name,
the same for every plugin. In your page's script:

```js
window.farmhand.onSave(async () => {         // Farmhand's Save was pressed
  // ...save what's typed on the page...
  return { ok: true, text: "Saved." };          // or { ok: false, text: "why not" }: shown beside the button
});
window.farmhand.changed(true);                 // there's something to save: the button lights up (false: greyed)
```

A page opened on its own (not inside Farmhand) has no such button: give it a Save of its own for that
(`window.farmhand.inFarmhand` says which).

## Across the network

A plugin may run on another machine, so the plugin API is answered on Farmhand's API port (4545), which the farm's
network reaches. It's never passed on by Farmhand's web page server (port 3636). It's kept to plugins by:

- **The token.** Every call needs one; Farmhand keeps only its hash and shows it once, when it's made.
- **The plugin's address.** With "Only accept its token from its own address" on (the default for a plugin added by
  its address), a token is refused from anywhere but the machine at the plugin's address (its name looked up, if it
  has one). A token copied elsewhere is no use. If your container moves (a new IP from DHCP, another port), the
  operator gives Farmhand its new address with **Change…** on the Plugins page: Farmhand fetches `<new address>/manifest`
  and takes the address only when its `id` is your plugin's. Your token and permissions stay the same, so nothing
  changes on your side; your calls are then taken from the new address.
- **How often.** Each token may make 10 calls a second (60 at once after a quiet spell); beyond that is 429.
- **Switching off.** A plugin switched off on the Plugins page has its token refused until it's switched on again.

The settings copy (the settings folder) lists the plugins added, their addresses, permissions and whether they're
on, never a token. Load all settings on a new Farmhand puts them back on the Plugins page as needing a new token.
