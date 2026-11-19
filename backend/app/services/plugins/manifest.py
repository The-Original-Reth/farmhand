"""
Checking a plugin's manifest (farmhand-plugin.json, see docs/plugins.md) before it's installed. Each problem is a
ValueError in plain words, shown to the operator as it is.
"""
from __future__ import annotations

import json
import re

API_VERSION = "1"  # the plugin API this Farmhand speaks (/plugin-api/v1/)

# What a plugin may be given, each in the words the Plugins page shows the operator
PERMISSIONS = {
    "printers:read": "see your printers: their names, how Farmhand reaches them and their addresses (never passwords or API keys)",
    "cameras:read": "see your printers' cameras and the addresses to stream them from",
    "prints:read": "see what each printer is printing and how far along it is, and hear when a print starts, pauses or ends",
    "farm:read": "see Farmhand's colours and the farm's time zone",
    # Reporting printers' status in place of Farmhand asking them (services/printer_reports.py): only for the Prusa
    # printers the operator switches to the plugin, one at a time, in each printer's PrusaLink section
    "printers:report": "report what your Prusa printers are doing (their state, temperatures and prints), in place of "
    "Farmhand asking their PrusaLink, for the printers you connect through it",
    # Starting the prints Farmhand sends those printers: Farmhand calls the manifest's "print" path with a one-time
    # ticket, and the plugin fetches the G-code with it (GET /plugin-api/v1/prints/{ticket}/file)
    "printers:print": "start the prints you send from Farmhand to the Prusa printers you connect through it (it is "
    "handed each G-code to send on)",
    # Only for a Stream plugin taking over from the Stream page Farmhand used to have; handed over once (handover.py)
    "stream:migrate": "take, once, a copy of the Stream page set-up this Farmhand saved before Stream became a plugin: "
    "its settings and saved layouts, the stream key and the YouTube sign-in (Farmhand keeps its copy)",
    # A stream plugin sending the stream designed in Stream control (services/stream_control): the design and its files
    "stream:read": "see the stream designed in Stream control (its layout, words, pictures and music) to send it to its site",
    # A plugin keeping a copy of its own settings in Farmhand's settings folder (services/plugins/backups.py), for
    # Farmhand to give back to it (the Plugins page's Restore settings): its secrets included, so said plainly
    "stream:backup": "keep a copy of its own settings with Farmhand's (in the settings folder), the stream key and the "
    "sign-in included, so they can be given back to it if it's set up again",
}

ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,39}$")


def check(raw) -> dict:
    """The manifest, checked and cut down to what Farmhand knows; ValueError says what's wrong with it."""
    if not isinstance(raw, dict):
        raise ValueError("The plugin's manifest (farmhand-plugin.json) isn't a JSON object.")
    plugin_id = raw.get("id")
    if not isinstance(plugin_id, str) or not ID.match(plugin_id):
        raise ValueError(
            "The plugin's id must be 1 to 40 lower-case letters, digits and dashes (not starting or ending with a "
            f"dash), like \"stream\". This one is {json.dumps(plugin_id)}."
        )
    name = _text(raw, "name", 80, required=True)
    version = raw.get("version")
    if not isinstance(version, str) or not VERSION.match(version):
        raise ValueError(f"The plugin's version must be like \"1.0.0\". This one is {json.dumps(version)}.")
    api = raw.get("farmhand_api")
    if api != API_VERSION:
        raise ValueError(
            f"This plugin was written for Farmhand's plugin API version {json.dumps(api)}, and this Farmhand speaks version "
            f"\"{API_VERSION}\". Look for a version of the plugin made for it."
        )
    port = raw.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError(f"The plugin's port must be a whole number from 1 to 65535. This one is {json.dumps(port)}.")
    permissions = raw.get("permissions", [])
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        raise ValueError("The plugin's permissions must be a list, like [\"printers:read\"].")
    unknown = [p for p in permissions if p not in PERMISSIONS]
    if unknown:
        raise ValueError(
            f"The plugin asks for {', '.join(repr(p) for p in unknown)}, which this Farmhand doesn't know. "
            f"It knows {', '.join(PERMISSIONS)}."
        )
    return {
        "id": plugin_id, "name": name, "version": version, "farmhand_api": api, "port": port,
        "author": _text(raw, "author", 120), "homepage": _text(raw, "homepage", 300),
        "permissions": list(dict.fromkeys(permissions)),
        "page": _page(raw.get("page")),
        "settings_page": _path(raw, "settings_page"),
        "health": _path(raw, "health"),
        "stream_control": _stream_control(raw.get("stream_control")),
        "print": _print(raw.get("print"), permissions),
        "backup": _backup(raw.get("backup"), permissions),
    }


def check_granted(manifest: dict, granted) -> list[str]:
    """The permissions the operator granted: a list, each one the plugin asked for."""
    if not isinstance(granted, list) or not all(isinstance(p, str) for p in granted):
        raise ValueError("The permissions granted must be a list, like [\"printers:read\"].")
    extra = [p for p in granted if p not in manifest["permissions"]]
    if extra:
        raise ValueError(
            f"The plugin didn't ask for {', '.join(repr(p) for p in extra)}: only what it asks for can be granted."
        )
    return list(dict.fromkeys(granted))


def describe(permissions: list[str]) -> list[dict]:
    """Each permission with what it lets the plugin do, in plain words."""
    return [{"permission": p, "means": PERMISSIONS[p]} for p in permissions if p in PERMISSIONS]


def _text(raw: dict, key: str, longest: int, required: bool = False) -> str | None:
    value = raw.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > longest:
        raise ValueError(f"The plugin's {key} must be text of 1 to {longest} characters.")
    return value.strip()


def _path(raw: dict, key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 200:
        raise ValueError(f"The plugin's {key} must be a path on the plugin starting with \"/\", like \"/health\".")
    return value


def _stream_control(raw) -> dict | None:
    """A stream plugin Stream control starts and stops: {"path": "/api/stream-control"} (GET it for how the stream is
    doing, POST <path>/start and <path>/stop), "site", where it streams to ("YouTube"), shown beside it, and
    "settings", a page of its own for that site's settings ("/?view=youtube-settings"), opened from Stream control."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("The plugin's stream_control must be an object, like {\"path\": \"/api/stream-control\", \"site\": \"YouTube\"}.")
    named = {"stream_control path": raw.get("path"), "stream_control site": raw.get("site"),
             "stream_control settings": raw.get("settings")}
    path = _path(named, "stream_control path")
    if path is None:
        raise ValueError("The plugin's stream_control needs a path, like \"/api/stream-control\".")
    # settings: a page of the plugin's own for its site's settings (stream key, sign-in...), opened from Stream control
    return {"path": path, "site": _text(named, "stream_control site", 40), "settings": _path(named, "stream_control settings")}


def _print(raw, permissions: list[str]) -> dict | None:
    """A plugin printers are connected through, which starts the prints Farmhand sends them: {"path": "/farmhand/print"}.
    Farmhand POSTs {ticket, printer_id, file, size} there and waits for {"sent": where it went}; see docs/plugins.md."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("The plugin's print must be an object, like {\"path\": \"/farmhand/print\"}.")
    path = _path({"print path": raw.get("path")}, "print path")
    if path is None:
        raise ValueError("The plugin's print needs a path, like \"/farmhand/print\".")
    if "printers:print" not in permissions:
        raise ValueError("The plugin's print needs the printers:print permission in its manifest's permissions.")
    return {"path": path}


def _backup(raw, permissions: list[str]) -> dict | None:
    """A plugin keeping a copy of its settings with Farmhand's (stream:backup): {"restore": "/api/farmhand-backup/restore"},
    the path Farmhand POSTs {saved_at} to when the operator restores them (the plugin then fetches them with GET
    /plugin-api/v1/backup and its token); see docs/plugins.md."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("The plugin's backup must be an object, like {\"restore\": \"/api/farmhand-backup/restore\"}.")
    path = _path({"backup restore": raw.get("restore")}, "backup restore")
    if path is None:
        raise ValueError("The plugin's backup needs a restore path, like \"/api/farmhand-backup/restore\".")
    if "stream:backup" not in permissions:
        raise ValueError("The plugin's backup needs the stream:backup permission in its manifest's permissions.")
    return {"restore": path}


def _page(raw) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("The plugin's page must be an object, like {\"menu\": \"Stream\", \"path\": \"/\"}.")
    named = {"page menu": raw.get("menu"), "page icon": raw.get("icon"), "page path": raw.get("path", "/")}
    return {"menu": _text(named, "page menu", 40, required=True), "icon": _text(named, "page icon", 40),
            "path": _path(named, "page path")}
