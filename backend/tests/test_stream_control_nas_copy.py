"""
Stream control works from Farmhand's own copy of its pictures and music (nas_copy.py), kept in step both ways with
the stream folder on the NAS: so the page and the stream plugins never wait on the NAS, and the NAS keeps a copy.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import storage
from app.services.stream_control import media, nas_copy

from .test_stream_control import PNG, switch


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(nas_copy, "_status", {"copied_at": None, "error": None, "copying": False})
    nas_copy._wake.clear()
    media._found = None
    yield
    media._found = None


def nas() -> Path:
    return nas_copy.nas_root_named()


def here() -> Path:
    return nas_copy.working_root()


def page_media(api) -> dict:
    return api.get("/stream-control").json()["media"]


def test_until_its_own_copy_is_filled_stream_control_works_from_the_nas_folder_then_from_its_own(api):
    switch(api)
    (nas() / "images").mkdir(parents=True)
    (nas() / "images" / "logo.png").write_bytes(PNG)
    (nas() / "slideshows" / "Prints").mkdir(parents=True)
    (nas() / "slideshows" / "Prints" / "a.png").write_bytes(PNG)
    (nas() / "music").mkdir()
    (nas() / "music" / "beat.mp3").write_bytes(b"ID3 beat")
    before = page_media(api)
    assert before["images"] == ["logo.png"] and before["copy"]["working"] is False  # (as before: the NAS folder)

    done = nas_copy.sync()
    assert done["copied_in"] == 3 and done["taken_out_here"] == done["taken_out_there"] == 0  # (the picture, the slideshow's, the track)
    assert (here() / "images" / "logo.png").read_bytes() == PNG
    after = page_media(api)
    assert after["copy"]["working"] is True and after["copy"]["error"] is None and after["copy"]["copied_at"]
    assert after["images"] == ["logo.png"] and after["slideshows"] == [{"name": "Prints", "images": ["a.png"]}]
    assert after["music"] == ["beat.mp3"]
    # the stamps the stream plugins compare are the same as the NAS folder's were: nothing is fetched again
    assert after["stamps"] == before["stamps"]
    # the page still shows the NAS folder, where people copy files in by hand
    assert Path(after["path"]) == nas()


def test_what_is_changed_through_farmhand_is_copied_to_the_nas_and_taken_out_there(api):
    switch(api)
    nas_copy.sync()  # (an empty NAS folder: Farmhand's own copy from the start)
    assert api.post("/stream-control/pictures", files=[("files", ("logo.png", PNG, "image/png"))]).status_code == 201
    assert not (nas() / "images" / "logo.png").exists()  # (not straight away: in the background)
    assert nas_copy.status()["waiting"] is True
    assert nas_copy.sync()["copied_out"] == 1
    assert (nas() / "images" / "logo.png").read_bytes() == PNG
    assert (nas() / "images" / "logo.png").stat().st_mtime_ns == (here() / "images" / "logo.png").stat().st_mtime_ns

    api.post("/stream-control/slideshows", json={"name": "Prints"})
    api.post("/stream-control/slideshows/Prints/pictures", files=[("files", ("a.png", PNG, "image/png"))])
    api.post("/stream-control/slideshows/Prints/blanks")
    nas_copy.sync()
    assert (nas() / "slideshows" / "Prints" / "a.png").exists() and (nas() / "slideshows" / "Prints" / media.ORDER_FILE).exists()

    # renamed through Farmhand: the new one copied, the old one taken out (its folder too, once empty)
    api.put("/stream-control/slideshows/Prints", json={"name": "Done"})
    nas_copy.sync()
    assert (nas() / "slideshows" / "Done" / "a.png").exists() and not (nas() / "slideshows" / "Prints").exists()

    assert api.delete("/stream-control/pictures/logo.png?confirm=true").status_code == 200
    assert nas_copy.sync()["taken_out_there"] == 1 and not (nas() / "images" / "logo.png").exists()
    # nothing else in the NAS folder is ever touched
    (nas() / "images" / "notes.txt").write_text("mine")
    nas_copy.sync()
    assert (nas() / "images" / "notes.txt").exists() and not (here() / "images" / "notes.txt").exists()


def test_what_is_copied_in_or_taken_out_on_the_nas_by_hand_is_brought_in(api):
    switch(api)
    nas_copy.sync()
    (nas() / "images" / "dropped.png").write_bytes(PNG)
    assert api.post("/stream-control/scan").json()["media"]["images"] == ["dropped.png"]  # Scan folder copies it in
    assert (here() / "images" / "dropped.png").exists()

    # replaced by hand: the newer one is copied in
    newer = nas() / "images" / "dropped.png"
    newer.write_bytes(PNG + b"new")
    os.utime(newer, ns=(newer.stat().st_atime_ns, newer.stat().st_mtime_ns + 5_000_000_000))
    nas_copy.sync()
    assert (here() / "images" / "dropped.png").read_bytes() == PNG + b"new"

    newer.unlink()  # taken out by hand
    assert nas_copy.sync()["taken_out_here"] == 1
    assert page_media(api)["images"] == []


def test_a_change_on_both_sides_keeps_the_newer(api):
    switch(api)
    nas_copy.sync()
    api.post("/stream-control/pictures", files=[("files", ("logo.png", PNG, "image/png"))])
    nas_copy.sync()
    mine, theirs = here() / "images" / "logo.png", nas() / "images" / "logo.png"
    mine.write_bytes(b"farmhand's")
    theirs.write_bytes(b"by hand, later")
    os.utime(theirs, ns=(theirs.stat().st_atime_ns, mine.stat().st_mtime_ns + 10_000_000_000))
    nas_copy.sync()
    assert mine.read_bytes() == theirs.read_bytes() == b"by hand, later"


def test_with_the_nas_away_stream_control_carries_on_from_its_own_copy_and_says_so(api, monkeypatch):
    switch(api)
    nas_copy.sync()
    api.post("/stream-control/pictures", files=[("files", ("logo.png", PNG, "image/png"))])

    def away():
        raise storage.StorageUnavailableError("The STL folder's share isn't connected.")

    monkeypatch.setattr(nas_copy, "nas_root", away)
    assert nas_copy.sync_quietly() is None
    got = api.post("/stream-control/scan").json()["media"]  # Scan folder: the NAS can't be read, the page still answers
    assert got["images"] == ["logo.png"] and got["error"] is None
    assert "share isn't connected" in got["copy"]["error"]
    assert api.get("/stream-control/pictures/logo.png").content == PNG  # the stream plugins still get every file


def test_a_nas_folder_found_emptied_takes_nothing_out_of_farmhands_copy(api):
    switch(api)
    nas_copy.sync()
    for n in ("a.png", "b.png", "c.png"):
        api.post("/stream-control/pictures", files=[("files", (n, PNG, "image/png"))])
    nas_copy.sync()
    for n in ("a.png", "b.png", "c.png"):
        (nas() / "images" / n).unlink()  # (the wrong folder mounted, say: none of them there)
    nas_copy.sync()
    assert page_media(api)["images"] == ["a.png", "b.png", "c.png"]
    assert sorted(p.name for p in (nas() / "images").iterdir()) == ["a.png", "b.png", "c.png"]  # (copied back out)


def test_the_page_always_says_how_the_copying_is_going_now_though_the_listing_is_kept(api):
    switch(api)
    first = page_media(api)  # (the listing kept from here until the folder is read again)
    assert first["copy"]["working"] is False and first["copy"]["copied_at"] is None
    nas_copy.sync()  # the first copying from the NAS finishes meanwhile (as the worker does it, in the background)
    now = page_media(api)
    assert now["copy"]["working"] is True and now["copy"]["copied_at"]
    nas_copy._status["error"] = "The STL folder's share isn't connected."
    assert page_media(api)["copy"]["error"] == "The STL folder's share isn't connected."
