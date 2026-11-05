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
    r = api.post(
        f"/projects/{pid}/parts",
        json={"name": "  Split  keyring 25mm ", "need": 24, "have": 10, "link": "amazon.com/dp/B0", "note": "pack of 50"},
    )
    assert r.status_code == 201
    part = r.json()["parts"][0]
    assert part == {
        "id": part["id"], "name": "Split keyring 25mm", "need": 24, "have": 10, "link": "https://amazon.com/dp/B0", "note": "pack of 50",
    }

    r = api.patch(f"/projects/{pid}/parts/{part['id']}", json={"need": 30, "link": ""})
    assert r.json()["parts"][0] == {**part, "need": 30, "link": None}  # have unchanged
    r = api.patch(f"/projects/{pid}/parts/{part['id']}", json={"have": 0})
    assert r.json()["parts"][0]["have"] == 0
    glue = api.post(f"/projects/{pid}/parts", json={"name": "Glue"}).json()["parts"][-1]
    assert (glue["need"], glue["have"], glue["link"], glue["note"]) == (1, 0, None, None)  # 1 needed, none yet

    for bad in ({"name": " "}, {"name": "x", "need": 0}, {"name": "x", "have": -1}, {"name": "x", "link": "javascript:alert(1)"}):
        assert api.post(f"/projects/{pid}/parts", json=bad).status_code == 422, bad

    assert api.delete(f"/projects/{pid}/parts/{part['id']}").status_code == 409  # no confirm=true
    assert [p["name"] for p in api.delete(f"/projects/{pid}/parts/{part['id']}", params={"confirm": "true"}).json()["parts"]] == ["Glue"]
    assert api.patch(f"/projects/{pid}/parts/999", json={"need": 2}).status_code == 404


def test_a_bom_from_the_template_adds_its_parts(api):
    pid = _project(api)
    api.post(f"/projects/{pid}/parts", json={"name": "Glue"}).raise_for_status()
    bom = (
        "Part,Need,Have,Link,Notes\n"
        "M3x12 screw,48,20,https://www.boltdepot.com/m3,hardware drawer B\n"
        "\n"
        '"Magnet, 6x3mm",24,,amazon.com/s?k=magnets,"N52, pack of 100"\n'
        "Heat-set insert M3,,,,\n"
    )
    r = _bom(api, pid, bom)
    assert r.status_code == 200 and r.json()["added"] == 3
    parts = r.json()["project"]["parts"]
    assert [(p["name"], p["have"], p["need"]) for p in parts] == [
        ("Glue", 0, 1), ("M3x12 screw", 20, 48), ("Magnet, 6x3mm", 0, 24), ("Heat-set insert M3", 0, 1),
    ]
    assert parts[2]["link"] == "https://amazon.com/s?k=magnets" and parts[2]["note"] == "N52, pack of 100"

    r = _bom(api, pid, "Part,Quantity\nKeyring,10\n", replace=True)  # an older BOM's Quantity is its Need
    assert [(p["name"], p["need"]) for p in r.json()["project"]["parts"]] == [("Keyring", 10)]  # replaced the list


def test_a_bom_with_mistakes_changes_nothing_and_says_which_rows(api):
    pid = _project(api)
    r = _bom(api, pid, "Part,Need,Have,Link\nScrew,lots,,\n,4,,\nMagnet,2,,javascript:x\nInsert,3,-1,\n")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "Row 2: How many are needed must be a whole number." in detail
    assert "Row 3: A part needs a name." in detail
    assert "Row 4: The link must be a web address" in detail
    assert "Row 5: How many you have must be from 0" in detail
    assert api.get(f"/projects/{pid}").json()["parts"] == []

    assert "needs a Part column" in _bom(api, pid, "Thing,Count\nScrew,2\n").json()["detail"]
    assert "empty" in _bom(api, pid, "").json()["detail"]
    assert "no parts" in _bom(api, pid, "Part,Need\n\n").json()["detail"]


def test_a_bom_from_excel_is_read_whatever_its_separator_or_encoding():
    # Excel's UTF-8 CSV starts with a byte-order mark; one set to a European language separates with ";"
    parts = read_bom("﻿Part;Qty;Notes\nSchraube M3;12;Größe 12mm\n".encode("utf-8"))
    assert parts == [{"name": "Schraube M3", "need": 12, "have": 0, "link": None, "note": "Größe 12mm"}]
    # an older Excel saves in its own encoding
    parts = read_bom("Part,Need,Notes\nWasher,4,Ø 3mm\n".encode("cp1252"))
    assert parts[0]["note"] == "Ø 3mm"
    # headings in any order and case, and other names for them
    assert read_bom(b"notes,PART,Link,In Stock\nblue,Cable tie,,3\n")[0] == {"name": "Cable tie", "need": 1, "have": 3, "link": None, "note": "blue"}
