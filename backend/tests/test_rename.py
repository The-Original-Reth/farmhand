from __future__ import annotations

import io
from urllib.parse import unquote

import pytest

from app.names import clean_file_name, download_name


@pytest.mark.parametrize("raw, extension, expected", [
    ("  Frog   keychain ", ".stl", "Frog keychain.stl"),
    ("Frog keychain.stl", ".stl", "Frog keychain.stl"),  # typed anyway: not doubled
    ("Frog keychain.STL", ".stl", "Frog keychain.stl"),  # the extension is always the file's own
    ("Frog keychain.obj", ".stl", "Frog keychain.obj.stl"),  # another extension can't replace it
    ("Frog plate", ".3mf", "Frog plate.3mf"),
    ("Frog plate. ", ".3mf", "Frog plate.3mf"),
])
def test_only_the_part_before_the_extension_changes(raw, extension, expected):
    assert clean_file_name(raw, extension=extension) == expected


@pytest.mark.parametrize("raw, message", [
    ("", "empty"), ("   ", "empty"), (".stl", "empty"), ("..", "empty"),
    ("a/b", "can't contain"), ('x"y', "can't contain"), ("a" * 252, "at most"),
])
def test_bad_names_are_refused(raw, message):
    with pytest.raises(ValueError, match=message):
        clean_file_name(raw, extension=".stl")


def test_a_download_keeps_the_stored_files_extension():
    assert download_name("Frog keychain", "/data/x/Frog_v1.stl") == "Frog keychain.stl"
    assert download_name("Frog keychain.stl", "/data/x/Frog_v1.stl") == "Frog keychain.stl"


@pytest.fixture()
def client(api):
    return api


def test_renaming_a_model_changes_its_name_and_its_download(client):
    m = client.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()
    r = client.patch(f"/source-models/{m['id']}", json={"name": "  Frog keychain  "})
    assert r.status_code == 200 and r.json()["name"] == "Frog keychain.stl"  # it stays an .stl
    assert client.get("/source-models").json()[0]["name"] == "Frog keychain.stl"
    assert client.patch(f"/source-models/{m['id']}", json={"name": "Frog keychain.3mf"}).json()["name"] == "Frog keychain.3mf.stl"
    client.patch(f"/source-models/{m['id']}", json={"name": "Frog keychain"})
    d = client.get(f"/source-models/{m['id']}/versions/1/download")
    assert d.status_code == 200 and "Frog keychain.stl" in unquote(d.headers["content-disposition"])
    assert client.patch(f"/source-models/{m['id']}", json={"name": "a/b"}).status_code == 422
    assert client.patch("/source-models/999", json={"name": "x"}).status_code == 404


def test_renaming_a_3mf_version_changes_its_name_and_its_download(client, sample_3mf_paths):
    p = client.post("/printers", json={"name": "VT 1190"}).json()
    m = client.post("/source-models", data={"name": "Frog.stl", "file_type": "STL"}, files={"file": ("Frog.stl", b"x" * 64)}).json()
    with open(sample_3mf_paths["frog_vt1190"], "rb") as f:
        b = client.post("/bundles", data={"source_model_ids": f"[{m['id']}]", "printer_id": str(p["id"])}, files={"threemf": ("frog.3mf", f.read())}).json()
    vid = b["versions"][0]["id"]
    r = client.patch(f"/bundles/versions/{vid}", json={"filename": "Frog plate (textured)"})
    assert r.status_code == 200 and r.json()["filename"] == "Frog plate (textured).3mf"  # .3mf added
    assert client.get(f"/bundles/{b['id']}").json()["versions"][0]["filename"] == "Frog plate (textured).3mf"
    assert client.patch(f"/bundles/versions/{vid}", json={"filename": "Frog plate.stl"}).json()["filename"] == "Frog plate.stl.3mf"
    client.patch(f"/bundles/versions/{vid}", json={"filename": "Frog plate (textured).3mf"})  # typed with it: not doubled
    d = client.get(f"/bundles/versions/{vid}/download/3mf")
    assert d.status_code == 200 and "Frog plate (textured).3mf" in unquote(d.headers["content-disposition"])
    assert client.patch(f"/bundles/versions/{vid}", json={"filename": ""}).status_code == 422
    assert client.patch("/bundles/versions/999", json={"filename": "x"}).status_code == 404
