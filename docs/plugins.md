# Writing a Farmhand plugin

A plugin is a program of your own that adds something to a print farm's Farmhand: a live stream, a dashboard, a
notifier. It runs in **its own Docker container**, with its own storage, written in any language. It never touches
Farmhand's database, files or other containers. It reads what it needs from Farmhand through the **plugin API**
described here, using a token the operator gave it, and only what the operator allowed.

**Start from the example:** [`plugins/hello`](../plugins/hello/README.md) is a small, working plugin (each printer and
its print's progress, updated live, in Farmhand's colours) with its Dockerfile, tests and instructions for making it
your own. It shows everything below in use: the manifest, the token and its refusals, events, a page that works inside
Farmhand, and settings kept in the plugin's own volume.

What's here (plugin API version 1): the manifest, adding a plugin on Farmhand's Plugins page, the token and
permissions, the read-only endpoints, the health check, and your plugin's page shown inside Farmhand. Farmhand doesn't
start or stop your container: the operator runs it (on Farmhand's machine or another one on the farm's network) the
way your instructions say, and adds it to Farmhand by its address.

## How a plugin is added

1. The operator starts your container, on any machine Farmhand can reach (for example `http://192.168.10.215:8080`),
   or beside Farmhand's own containers on its Docker network (`http://<id>:<port>`).
2. On Farmhand's **Plugins** page they type that address. Farmhand asks it for `GET <address>/manifest`, checks it,
   and shows its name and the permissions it asks for in plain words. They can untick permissions, and choose whether
   Farmhand takes your token only from that address (on by default).
3. Once they say yes, Farmhand shows them your plugin's `FARMHAND_URL` and `FARMHAND_TOKEN`, once. They set those as
   environment variables for your container and restart it.

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
| `page` | no | A page in Farmhand's menu: `menu` (its label, up to 40 characters), `icon` (optional: `video`, `camera`, `chart`, `bell` or `dashboard`; a puzzle piece otherwise), `path` on your plugin (default `/`). See "Your page inside Farmhand" |
| `permissions` | no | What it needs to read (below). Ask only for what you use: the operator sees each one in plain words before saying yes |
| `settings_page` | no | A path on your plugin shown on Farmhand's Settings page |
| `health` | no | A path that answers 2xx while your plugin is well. Farmhand asks it every 30 seconds (`/manifest` when there's none) and shows the operator "running", "running, with a problem" (any other answer: send a short plain-words reason as text, like "Farmhand refused this plugin's token: make a new one on the Plugins page"; your page is still shown) or "not answering" (nothing answered: Farmhand shows that in place of your page) |

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
`error` (`null` on `printer.reachable`). The stream opens with a comment line (`: connected`), and another
(`: still here`) comes every 15 seconds while nothing happens, so you can tell the connection is alive: one silent for
much longer than that has gone (time your reads out at 45 seconds or so). Events aren't kept: one that happens while
you're not connected is missed, so after connecting, ask `GET /printers/{id}/print` for how things stand. Reconnect if
the connection drops (Farmhand restarting ends it). Events say when a print starts, pauses or ends, not how it creeps
along: for progress, ask each printer's print now and then (every 20 seconds or so is plenty).

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

## Across the network

A plugin may run on another machine, so the plugin API is answered on Farmhand's API port (4545), which the farm's
network reaches. It's never passed on by Farmhand's web page server (port 3636). It's kept to plugins by:

- **The token.** Every call needs one; Farmhand keeps only its hash and shows it once, when it's made.
- **The plugin's address.** With "Only accept its token from its own address" on (the default for a plugin added by
  its address), a token is refused from anywhere but the machine at the plugin's address (its name looked up, if it
  has one). A token copied elsewhere is no use.
- **How often.** Each token may make 10 calls a second (60 at once after a quiet spell); beyond that is 429.
- **Switching off.** A plugin switched off on the Plugins page has its token refused until it's switched on again.

The settings copy (the settings folder) lists the plugins added, their addresses, permissions and whether they're
on, never a token. Load all settings on a new Farmhand puts them back on the Plugins page as needing a new token.
