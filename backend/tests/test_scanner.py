from __future__ import annotations

import os

import pytest

from app import scanner


def _touch(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


@pytest.fixture()
def tree(tmp_path):
    """A NAS folder as a person might leave it: some model files, some junk, some housekeeping."""
    root = tmp_path / "stl"
    _touch(root / "Frog.stl", 111)
    _touch(root / "frog2.STL")  # extensions aren't case-sensitive
    _touch(root / "part.STP")
    _touch(root / "Animals" / "Shark.obj")
    _touch(root / "Animals" / "deep" / "bracket.step")
    _touch(root / "Known.stl")
    # things that must NOT be offered
    _touch(root / "readme.txt")
    _touch(root / "photo.jpg")
    _touch(root / ".hidden.stl")
    _touch(root / ".farmhand-storage")
    _touch(root / "upload.stl.part")
    _touch(root / "stl")  # no extension, just a name
    for skipped in (".cache", "@eaDir", "#recycle", "@Recycle", "System Volume Information", "$RECYCLE.BIN"):
        _touch(root / skipped / "inside.stl")
    os.symlink(root / "Frog.stl", root / "link.stl")  # a link to a file
    os.symlink(root / "Animals", root / "linkdir")  # a link to a folder (would double-count its contents)
    return root


def test_finds_model_files_anywhere_under_the_folder(tree):
    found, truncated = scanner.scan_folder(tree, known={scanner.normalise(tree / "Known.stl")})
    assert not truncated
    assert [(f.name, f.folder, f.file_type) for f in found] == [
        ("bracket.step", "Animals/deep", "STEP"),
        ("Shark.obj", "Animals", "OBJ"),
        ("Frog.stl", "", "STL"),
        ("frog2.STL", "", "STL"),
        ("part.STP", "", "STEP"),
    ]
    frog = next(f for f in found if f.name == "Frog.stl")
    assert frog.size_bytes == 111 and frog.path == str(tree / "Frog.stl")


def test_skips_what_is_already_in_the_library(tree):
    everything, _ = scanner.scan_folder(tree, known=set())
    assert "Known.stl" in {f.name for f in everything}
    known = {scanner.normalise(f.path) for f in everything}
    again, _ = scanner.scan_folder(tree, known=known)
    assert again == []  # a second scan right after importing finds nothing


def test_skips_junk_housekeeping_partial_uploads_and_links(tree):
    names = {f.name for f in scanner.scan_folder(tree, known=set())[0]}
    assert names == {"Frog.stl", "frog2.STL", "part.STP", "Shark.obj", "bracket.step", "Known.stl"}
    # in particular none of: .hidden.stl, upload.stl.part, anything under @eaDir/#recycle/…, link.stl, or linkdir's copies


def test_stops_at_the_limit_and_says_so(tmp_path):
    root = tmp_path / "many"
    for i in range(30):
        _touch(root / f"m{i:02d}.stl")
    found, truncated = scanner.scan_folder(root, known=set(), limit=10)
    assert len(found) == 10 and truncated
    found, truncated = scanner.scan_folder(root, known=set(), limit=30)
    assert len(found) == 30 and not truncated  # exactly the limit isn't "more than shown"


def test_an_unreadable_folder_is_skipped_not_fatal(tree, monkeypatch):
    real = os.scandir

    def flaky(path):
        if str(path).endswith("deep"):
            raise PermissionError("denied")
        return real(path)

    monkeypatch.setattr(scanner.os, "scandir", flaky)
    names = {f.name for f in scanner.scan_folder(tree, known=set())[0]}
    assert "bracket.step" not in names and "Shark.obj" in names


def test_a_missing_folder_finds_nothing(tmp_path):
    assert scanner.scan_folder(tmp_path / "nope", known=set()) == ([], False)


def test_file_types():
    assert [scanner.file_type_for(n) for n in ("a.stl", "a.STL", "a.obj", "a.step", "a.STP", "a.3mf", "stl", "a.stl.txt")] == [
        "STL", "STL", "OBJ", "STEP", "STEP", None, None, None]
