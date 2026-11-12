"""
What follows a successful change made through the API, by where it was made: the settings folder's copy (printers/
and models/ files, config_service.request_mirror), a project's record in its folder (project_records), a model's or
3MF's record beside its files (library_records). All written shortly after, in the background.

A new mutating route under a prefix not handled here writes none of them: add it to _what_changed (and below).
"""
from __future__ import annotations

from fastapi import FastAPI, Request

from .services import config_service, library_records, project_records

MUTATING = ("POST", "PUT", "PATCH", "DELETE")


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def after_a_change(request: Request, call_next):
        response = await call_next(request)
        if request.method in MUTATING and response.status_code < 400:
            changed(request.url.path)
        return response


def changed(path: str) -> None:
    scope = _what_changed(path)
    if scope is not None:
        config_service.request_mirror(scope)
    parts = path.strip("/").split("/")
    one = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    if parts[0] == "projects":
        project_records.request_write(one)
    if parts[0] == "source-models":
        library_records.request_write("model", one)
    if parts[0] == "bundles" and parts[-1] != "inspect":
        library_records.request_write("bundle", one)


def _what_changed(path: str) -> "config_service.MirrorScope | None":
    """Which files of the settings copy a successful change at this path touches (None: none of them)."""
    parts = path.strip("/").split("/")
    if parts[0] == "printers":
        if len(parts) > 2 and parts[1].isdigit():
            return config_service.MirrorScope(printers={int(parts[1])})  # its notes, a sync, its service...
        return config_service.EVERYTHING  # added, renamed, retired or deleted: file names and models' files follow
    if parts[0] in ("bundles", "source-models"):
        if parts[-1] == "inspect":
            return None  # only reads the 3MF
        if parts[-1] == "print":
            return config_service.MirrorScope(printers=True)  # a print sent: its printer's history may have it
        return config_service.MirrorScope(models=True)
    if parts[0] == "plugins":
        if parts[-1] == "preview" or (len(parts) > 2 and parts[2] == "page"):
            return None  # only looks at a plugin, or is its own page asking it something
        return config_service.MirrorScope()  # the settings file's list of plugins and what they were granted (never a token)
    return None
