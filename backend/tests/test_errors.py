from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.errors import NotFound, answer_errors


@pytest.mark.parametrize("error, status", [(NotFound("No printer with id 9"), 404), (ValueError("Give it a name"), 422)])
def test_errors_become_answers_with_their_own_message(error, status):
    with pytest.raises(HTTPException) as caught, answer_errors():
        raise error
    assert caught.value.status_code == status and caught.value.detail == str(error)


def test_a_route_can_say_what_a_refusal_is():
    with pytest.raises(HTTPException) as caught, answer_errors(409):
        raise ValueError("A printer named 'VT 1190' already exists")
    assert caught.value.status_code == 409


def test_anything_else_is_a_real_fault_and_is_not_hidden():
    with pytest.raises(KeyError), answer_errors():  # a KeyError is a LookupError, but a bug, not "not found"
        raise KeyError("oops")


@pytest.mark.parametrize("method, path, kwargs", [
    ("get", "/bundles/versions/999/download/3mf", {}),
    ("get", "/bundles/versions/999/download/gcode", {}),
    ("patch", "/bundles/versions/999/monument", {"json": {"monument": True, "note": "keep"}}),
    ("patch", "/bundles/versions/999", {"json": {"filename": "x"}}),
    ("put", "/bundles/999/star", {"json": {"version_id": None}}),
    ("put", "/bundles/999/notes", {"json": {"notes": "x", "base_revision": 0}}),
    ("put", "/printers/999/notes", {"json": {"notes": "x", "base_revision": 0}}),
    ("put", "/source-models/999/notes", {"json": {"notes": "x", "base_revision": 0}}),
    ("patch", "/source-models/999", {"json": {"name": "x"}}),
    ("post", "/source-models/999/versions", {"files": {"file": ("a.stl", b"x" * 64)}}),
    ("post", "/bundles/999/versions", {"files": {"threemf": ("a.3mf", b"PK")}}),
])
def test_something_missing_is_always_a_404(api, method, path, kwargs):
    r = getattr(api, method)(path, **kwargs)
    assert r.status_code == 404, r.text
    assert r.json()["detail"].startswith("No ")
