"""
The lists the page loads (every printer, model and 3MF) cost the same few queries however many rows there are, and
a list of 3MF versions never reads their parsed settings (often 30-60 KB each): only one version's detail does.
"""
from __future__ import annotations

import contextlib

from sqlalchemy import event
from sqlalchemy.engine import Engine


@contextlib.contextmanager
def queries():
    seen: list[str] = []

    def note(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", note)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", note)


def _farm(api, sample_3mf_paths, n):
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        data = f.read()
    pid = api.post("/printers", json={"name": "VT 1190"}).json()["id"]
    for i in range(n):
        mid = api.post("/source-models", data={"name": f"M{i}.stl", "file_type": "STL"}, files={"file": (f"M{i}.stl", b"x" * 64)}).json()["id"]
        api.put(f"/source-models/{mid}/notes", json={"notes": "n", "base_revision": 0})
        b = api.post("/bundles", data={"source_model_ids": f"[{mid}]", "printer_id": str(pid)}, files={"threemf": ("G.3mf", data)}).json()
        api.post(f"/bundles/{b['id']}/versions", files={"threemf": ("G.3mf", data)})
        api.put(f"/bundles/{b['id']}/notes", json={"notes": "n", "base_revision": 0})
    return pid


def _count(api, path):
    with queries() as seen:
        assert api.get(path).status_code == 200
    return seen


def test_list_queries_dont_grow_with_the_number_of_rows(api, sample_3mf_paths):
    pid = _farm(api, sample_3mf_paths, 2)
    few = {p: len(_count(api, p)) for p in ("/bundles", "/source-models", "/printers", f"/printers/{pid}/bundles")}
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        data = f.read()
    for i in range(4):  # four more models, each with a 3MF of two versions
        mid = api.post("/source-models", data={"name": f"N{i}.stl", "file_type": "STL"}, files={"file": (f"N{i}.stl", b"x" * 64)}).json()["id"]
        b = api.post("/bundles", data={"source_model_ids": f"[{mid}]", "printer_id": str(pid)}, files={"threemf": ("G.3mf", data)}).json()
        api.post(f"/bundles/{b['id']}/versions", files={"threemf": ("G.3mf", data)})
        api.post("/printers", json={"name": f"P{i}"})
    many = {p: len(_count(api, p)) for p in few}
    assert many == few


def test_a_list_of_3mfs_never_reads_their_settings_but_one_version_does(api, sample_3mf_paths):
    _farm(api, sample_3mf_paths, 1)
    listed = _count(api, "/bundles")
    assert not any("settings" in q for q in listed)
    vid = api.get("/bundles").json()[0]["versions"][0]["id"]
    detail = api.get(f"/bundles/versions/{vid}")
    assert detail.status_code == 200 and detail.json()["settings"]  # still there when it's asked for
