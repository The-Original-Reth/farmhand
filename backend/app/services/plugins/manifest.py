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
    # A slicer plugin (library.py): the files sent to it, the 3MF it slices from them, the G-code it makes
    "library:read": "open the models, 3MFs and project files you send it from Farmhand (only those you send it)",
    "library:write": "save the 3MFs it slices into Farmhand, next to the files they were sliced from: as a new 3MF or "
    "its next version, in Models or in the project the files came from, and a new project for a 3MF sliced from "
    "several models",
    "prints:send": "send the G-code it makes to one of your printers and start printing it (never while the printer "
    "is busy)",
    # Only for a Stream plugin taking over from the Stream page Farmhand used to have; handed over once (handover.py)
    "stream:migrate": "take, once, a copy of the Stream page set-up this Farmhand saved before Stream became a plugin: "
    "its settings and saved layouts, the stream key and the YouTube sign-in (Farmhand keeps its copy)",
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
        "send_files": _send_files(raw.get("send_files"), permissions, raw.get("page")),
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


def _page(raw) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("The plugin's page must be an object, like {\"menu\": \"Stream\", \"path\": \"/\"}.")
    named = {"page menu": raw.get("menu"), "page icon": raw.get("icon"), "page path": raw.get("path", "/")}
    return {"menu": _text(named, "page menu", 40, required=True), "icon": _text(named, "page icon", 40),
            "path": _path(named, "page path")}


SEND_KINDS = ("stl", "obj", "3mf")  # what Farmhand's "Send to <plugin>" offers to send (docs/plugins.md)


def _send_files(raw, permissions: list[str], page) -> dict | None:
    """
    {label, path, kinds}: a "Send to <label>" Farmhand puts on the models, 3MFs and project files of those kinds,
    which opens the plugin's page at `path` with the files' refs (?file=model:12&file=3mf:40...). Needs library:read,
    to open them.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("The plugin's send_files must be an object, like {\"label\": \"Slicer\", \"path\": \"/open\"}.")
    if page is None:
        raise ValueError("A plugin that files can be sent to (send_files) needs a page: that's where they open.")
    if "library:read" not in permissions:
        raise ValueError("A plugin that files can be sent to (send_files) must ask for library:read, to open them.")
    named = {"send_files label": raw.get("label"), "send_files path": raw.get("path", "/")}
    kinds = raw.get("kinds", list(SEND_KINDS))
    if not isinstance(kinds, list) or not kinds or any(k not in SEND_KINDS for k in kinds):
        raise ValueError(f"The plugin's send_files kinds must be a list of {', '.join(SEND_KINDS)}.")
    return {"label": _text(named, "send_files label", 40, required=True), "path": _path(named, "send_files path"),
            "kinds": list(dict.fromkeys(kinds))}
