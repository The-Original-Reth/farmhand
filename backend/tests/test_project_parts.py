from __future__ import annotations

import io

from app.services.project_parts import read_bom


def _project(api, name="Keychains"):
    return api.post("/projects", json={"name": name}).json()["id"]


def _bom(api, pid, text, replace=False, encoding="utf-8"):
    data = text.encode(encoding) if isinstance(text, str) else text
    return api.post(f"/projects/{pid}/parts/bom", files={"file": ("bom.csv", io.BytesIO(data))}, data={"replace": str(replace).lower()})


def test_a_part_is_added_changed_and_removed(api):
    pid = _project(api)
    r = api.post(f"/projects/{pid}/parts", json={"name": "  Split  keyring 25mm ", "quantity": 24, "link": "amazon.com/dp/B0", "note": "pack of 50"})
    assert r.status_code == 201
    part = r.json()["parts"][0]
    assert part == {"id": part["id"], "name": "Split keyring 25mm", "quantity": 24, "link": "https://amazon.com/dp/B0", "note": "pack of 50"}

    r = api.patch(f"/projects/{pid}/parts/{part['id']}", json={"quantity": 30, "link": ""})
    assert r.json()["parts"][0] == {**part, "quantity": 30, "link": None}

    for bad in ({"name": " "}, {"name": "x", "quantity": 0}, {"name": "x", "link": "javascript:alert(1)"}):
        assert api.post(f"/projects/{pid}/parts", json=bad).status_code == 422, bad

    assert api.delete(f"/projects/{pid}/parts/{part['id']}").status_code == 409  # no confirm=true
    assert api.delete(f"/projects/{pid}/parts/{part['id']}", params={"confirm": "true"}).json()["parts"] == []
    assert api.patch(f"/projects/{pid}/parts/999", json={"quantity": 2}).status_code == 404


def test_a_bom_from_the_template_adds_its_parts(api):
    pid = _project(api)
    api.post(f"/projects/{pid}/parts", json={"name": "Glue"}).raise_for_status()
    bom = (
        "Part,Quantity,Link,Notes\n"
        "M3x12 screw,48,https://www.boltdepot.com/m3,hardware drawer B\n"
        "\n"
        '"Magnet, 6x3mm",24,amazon.com/s?k=magnets,"N52, pack of 100"\n'
        "Heat-set insert M3,,,\n"
    )
    r = _bom(api, pid, bom)
    assert r.status_code == 200 and r.json()["added"] == 3
    parts = r.json()["project"]["parts"]
    assert [(p["name"], p["quantity"]) for p in parts] == [("Glue", 1), ("M3x12 screw", 48), ("Magnet, 6x3mm", 24), ("Heat-set insert M3", 1)]
    assert parts[2]["link"] == "https://amazon.com/s?k=magnets" and parts[2]["note"] == "N52, pack of 100"

    r = _bom(api, pid, "Part,Quantity\nKeyring,10\n", replace=True)
    assert [p["name"] for p in r.json()["project"]["parts"]] == ["Keyring"]  # replaced the list


def test_a_bom_with_mistakes_changes_nothing_and_says_which_rows(api):
    pid = _project(api)
    r = _bom(api, pid, "Part,Quantity,Link\nScrew,lots,\n,4,\nMagnet,2,javascript:x\nInsert,3,\n")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "Row 2: The quantity must be a whole number." in detail
    assert "Row 3: A part needs a name." in detail
    assert "Row 4: The link must be a web address" in detail
    assert api.get(f"/projects/{pid}").json()["parts"] == []

    assert "needs a Part column" in _bom(api, pid, "Thing,Count\nScrew,2\n").json()["detail"]
    assert "empty" in _bom(api, pid, "").json()["detail"]
    assert "no parts" in _bom(api, pid, "Part,Quantity\n\n").json()["detail"]


def test_a_bom_from_excel_is_read_whatever_its_separator_or_encoding():
    # Excel's UTF-8 CSV starts with a byte-order mark; one set to a European language separates with ";"
    parts = read_bom("﻿Part;Qty;Notes\nSchraube M3;12;Größe 12mm\n".encode("utf-8"))
    assert parts == [{"name": "Schraube M3", "quantity": 12, "link": None, "note": "Größe 12mm"}]
    # an older Excel saves in its own encoding
    parts = read_bom("Part,Quantity,Notes\nWasher,4,Ø 3mm\n".encode("cp1252"))
    assert parts[0]["note"] == "Ø 3mm"
    # headings in any order and case
    assert read_bom(b"notes,PART,Link\nblue,Cable tie,\n")[0] == {"name": "Cable tie", "quantity": 1, "link": None, "note": "blue"}
