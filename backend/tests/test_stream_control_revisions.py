"""
Stream control saved from two places at once (two tabs, a slideshow renamed, Load all settings): a save based on an
older copy of the design, the saved layouts or the schedule is refused (409) rather than putting back what the other
save changed, and two saves at the very same moment each get a revision of their own.
"""
from __future__ import annotations

from app.services import app_settings
from app.services.stream_control import design, layouts

from .factories import api_db
from .test_stream_control import CAMERA, _fresh, switch  # noqa: F401  (_fresh: autouse)


def test_a_design_save_from_an_older_copy_is_refused(api):
    switch(api)
    first = api.get("/stream-control").json()["design"]["revision"]
    r = api.put("/stream-control", json={"title": "Tab one", "base_revision": first})
    assert r.status_code == 200, r.text
    assert r.json()["design"]["revision"] == first + 1

    # the other tab still has the first copy: nothing it sends is saved
    r = api.put("/stream-control", json={"description": "Tab two", "base_revision": first})
    assert r.status_code == 409
    assert "changed somewhere else" in r.json()["detail"] and "Reload" in r.json()["detail"]
    d = api.get("/stream-control").json()["design"]
    assert (d["title"], d["description"], d["revision"]) == ("Tab one", "", first + 1)

    # without base_revision (Copy layout, an older page) it's saved over whatever is there, as before
    assert api.put("/stream-control", json={"description": "Anyway"}).json()["design"]["revision"] == first + 2
    assert api.put("/stream-control", json={"title": "x", "base_revision": "1"}).status_code == 422


def test_two_design_saves_at_once_both_count(api, monkeypatch):
    """A save that meets another one between reading the design and writing it reads it again: neither change is
    lost, and the revision goes up once for each (a plugin following by revision misses neither)."""
    switch(api)
    db = api_db(api)
    start = design.settings(db)["revision"]
    real = design._read
    other = []

    def meanwhile(session):
        got = real(session)
        if not other:  # another save lands after this one has read the design
            other.append(1)
            design.save(api_db(api), {"description": "From the other tab"})
        return got

    monkeypatch.setattr(design, "_read", meanwhile)
    after = design.save(db, {"title": "From this tab"})
    assert (after["title"], after["description"]) == ("From this tab", "From the other tab")
    assert after["revision"] == start + 2


def test_a_write_over_a_value_that_changed_is_refused(api):
    db = api_db(api)
    assert app_settings.swap(db, "k", None, "one")
    assert not app_settings.swap(db, "k", None, "two")  # (it's there now)
    assert not app_settings.swap(db, "k", "zero", "two")
    assert app_settings.swap(db, "k", "one", "two") and app_settings.fresh(db, "k") == "two"


def test_saved_layouts_from_an_older_copy_are_refused(api):
    switch(api)
    rev = api.get("/stream-control").json()["layouts_revision"]
    one = [{"name": "Night", "cols": 1, "rows": 1, "cells": [{"camera": CAMERA}]}]
    r = api.put(f"/stream-control/layouts?base_revision={rev}", json=one)
    assert r.status_code == 200, r.text
    assert r.json()["layouts_revision"] != rev

    r = api.put(f"/stream-control/layouts?base_revision={rev}", json=[{"name": "Day", "cols": 1, "rows": 1, "cells": [None]}])
    assert r.status_code == 409 and "saved layouts were changed" in r.json()["detail"]
    assert [lay["name"] for lay in api.get("/stream-control").json()["layouts"]] == ["Night"]


def test_a_renamed_slideshow_follows_into_layouts_saved_meanwhile(api, monkeypatch):
    switch(api)
    db = api_db(api)
    layouts.save(db, [{"name": "A", "cols": 1, "rows": 1, "cells": [{"slideshow": "Prints"}]}])
    real = layouts._read
    other = []

    def meanwhile(session):
        got = real(session)
        if not other:
            other.append(1)
            layouts.save(api_db(api), [*layouts.layouts(api_db(api)), {"name": "B", "cols": 1, "rows": 1, "cells": [{"slideshow": "Prints"}]}])
        return got

    monkeypatch.setattr(layouts, "_read", meanwhile)
    assert design.rename_slideshow(db, "Prints", "Done") == 2
    kept = layouts.layouts(db)
    assert [(lay["name"], lay["cells"][0]["slideshow"]) for lay in kept] == [("A", "Done"), ("B", "Done")]


def test_a_schedule_from_an_older_copy_is_refused(api):
    switch(api)
    rev = api.get("/stream-control").json()["schedule_revision"]
    entry = {"days": [0], "start": "08:00", "stop": None, "streams": "all"}
    r = api.put("/stream-control/schedule", json={"on": True, "entries": [entry], "base_revision": rev})
    assert r.status_code == 200, r.text
    r = api.put("/stream-control/schedule", json={"on": False, "entries": [], "base_revision": rev})
    assert r.status_code == 409 and "schedule was changed" in r.json()["detail"]
    assert api.get("/stream-control").json()["schedule"]["on"] is True
