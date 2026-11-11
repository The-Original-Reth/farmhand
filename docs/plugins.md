# Writing a Farmhand plugin

A plugin is a program of your own that adds something to a print farm's Farmhand: a live stream, a dashboard, a
notifier. It runs in **its own Docker container**, with its own storage, written in any language. It never touches
Farmhand's database, files or other containers. It reads what it needs from Farmhand through the **plugin API**
described here, using a token the operator gave it, and only what the operator allowed.

What's here so far (plugin API version 1): the manifest, the token and permissions, and the read-only endpoints.
Installing a plugin from the Plugins page, running its container and showing its page inside Farmhand come in later
releases; this page will grow with them.

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
| `port` | yes | The port your container listens on, inside Docker's network |
| `author`, `homepage` | no | Shown to the operator |
| `page` | no | A page in Farmhand's menu: `menu` (its label, up to 40 characters), `icon` (optional), `path` on your plugin (default `/`) |
| `permissions` | no | What it needs to read (below). Ask only for what you use: the operator sees each one in plain words before saying yes |
| `settings_page` | no | A path on your plugin shown on Farmhand's Settings page |
| `health` | no | A path that answers 200 while your plugin is well |

Farmhand checks the manifest when the plugin is installed, and says in plain words what's wrong with one it won't take.

## Permissions

| Permission | What the operator is told it lets the plugin do | Endpoints |
|---|---|---|
| `printers:read` | see your printers: their names, how Farmhand reaches them and their addresses (never passwords or API keys) | `GET /printers` |
| `cameras:read` | see your printers' cameras and the addresses to stream them from | `GET /cameras` |
| `prints:read` | see what each printer is printing and how far along it is, and hear when a print starts, pauses or ends | `GET /printers/{id}/print`, `GET /events` |
| `farm:read` | see Farmhand's colours and the farm's time zone | `GET /farm` |

The operator grants some or all of the permissions the manifest asks for, never more. There are no write permissions
yet; they'll be added one at a time, when a plugin needs one.

## Reaching Farmhand

Your container is given two environment variables:

- `FARMHAND_URL`: where the plugin API is, e.g. `http://api:4545/plugin-api/v1`
- `FARMHAND_TOKEN`: your plugin's token

Send the token with every call:

```
GET $FARMHAND_URL/printers
Authorization: Bearer $FARMHAND_TOKEN
```

- No token, or one Farmhand doesn't know, is **401** (with `WWW-Authenticate: Bearer`). A token stops working when
  the operator makes a new one for the plugin, removes the plugin, or turns it off: read `FARMHAND_TOKEN` again when
  your container restarts.
- A call outside your plugin's permissions is **403**, naming the permission it needs.
- Every error is JSON, `{"detail": "..."}`, in words meant for the operator: show it as it is.

Answers are kept by Farmhand for a few seconds (printers 5 s, cameras 15 s, a print 3 s, the farm 10 s), so asking more
often than that gets the same answer. Ask for a print's progress every few seconds at most, and use `/events` rather
than asking every printer in a loop.

The plugin API is meant to be reached only from inside Docker's network, by plugin containers. See "Kept inside
Docker" below.

## The endpoints

All under `/plugin-api/v1`. Every answer is a JSON object (so fields can be added later).

### `GET /me` (any valid token)

Which plugin the token is, and what it may read. A good first call, to check the token works.

```json
{ "plugin_id": "stream", "permissions": ["cameras:read", "printers:read", "prints:read"], "api_version": "1" }
```

### `GET /printers` (`printers:read`)

Every printer in service (retired ones are left out), by name. `connection_type` is `moonraker` (Klipper) or
`prusalink` (Prusa). Addresses that don't apply to the printer's kind are `null`. Never an API key or password.

```json
{
  "printers": [
    {
      "id": 1, "name": "VT 1190", "kind": "Voron Trident", "connection_type": "moonraker",
      "addresses": {
        "wired_ip": "10.0.6.21", "wireless_ip": "10.0.7.21",
        "moonraker_url": "http://10.0.6.21:7125", "mainsail_url": "http://10.0.6.21/",
        "prusalink_url": null, "camera_address": null
      }
    },
    {
      "id": 2, "name": "Core One", "kind": null, "connection_type": "prusalink",
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
ffmpeg can read: `kind` is `mjpeg` or `rtsp`, `url` the address, and `ffmpeg_input` the options Farmhand's own stream
uses to read it (reconnecting, timeouts), ending in `-i <url>`. `rotation` and the flips are as set in Mainsail;
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
`error` (`null` on `printer.reachable`). A comment line (`: still here`) comes every 15 seconds while nothing
happens, so you can tell the connection is alive. Events aren't kept: one that happens while you're not connected
is missed, so after connecting, ask `GET /printers/{id}/print` for how things stand. Reconnect if the connection
drops (Farmhand restarting ends it).

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

## Versions

- `/plugin-api/v1` stays as it is. It only ever **gains**: new endpoints, new fields in an answer, new event types,
  new permissions. Nothing is renamed, retyped or taken away. So ignore fields and event types you don't know.
- A change that would break a plugin is a new version, `/plugin-api/v2`, served beside v1 for a while so plugins
  can move over.
- `farmhand_api` in your manifest says which version you wrote for.

## Kept inside Docker

The plugin API is for plugin containers only, never the network outside. Today:

- The web server (nginx, port 3636) doesn't pass `/plugin-api/` on, so it can't be reached through Farmhand's pages.
- Every call needs a plugin's token, kept by Farmhand only as a hash and shown once when made.
- But the routes are served by the API container, whose port (4545) is published so the browser can reach the API:
  someone on the farm's network holding a token could call them there.

When Farmhand starts running plugin containers (the next release), the plugin API moves to a port of the API
container's own that isn't published, on a Docker network shared only with the plugins, and the API's published
port stops answering `/plugin-api/`. `FARMHAND_URL` will point there; a plugin that reads it needs no change.
