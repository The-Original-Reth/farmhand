from __future__ import annotations


def test_a_project_is_made_listed_renamed_and_deleted(api):
    r = api.post("/projects", json={"name": "  Christmas   ornaments "})
    assert r.status_code == 201
    p = r.json()
    assert p["name"] == "Christmas ornaments"  # spaces tidied

    api.post("/projects", json={"name": "art fair"}).raise_for_status()
    assert [x["name"] for x in api.get("/projects").json()] == ["art fair", "Christmas ornaments"]  # by name, any case
    assert api.get(f"/projects/{p['id']}").json()["name"] == "Christmas ornaments"

    r = api.patch(f"/projects/{p['id']}", json={"name": "Ornaments"})
    assert r.status_code == 200 and r.json()["name"] == "Ornaments"

    assert api.delete(f"/projects/{p['id']}").status_code == 409  # no confirm=true
    assert api.delete(f"/projects/{p['id']}", params={"confirm": "true"}).status_code == 204
    assert api.get(f"/projects/{p['id']}").status_code == 404


def test_a_project_name_must_be_given_and_not_taken(api):
    pid = api.post("/projects", json={"name": "Ornaments"}).json()["id"]
    other = api.post("/projects", json={"name": "Fair"}).json()["id"]
    r = api.post("/projects", json={"name": "ornaments"})
    assert r.status_code == 409 and "already a project called Ornaments" in r.json()["detail"]
    assert api.post("/projects", json={"name": "   "}).status_code == 409
    assert api.post("/projects", json={"name": "x" * 201}).status_code == 409
    assert api.patch(f"/projects/{other}", json={"name": "ORNAMENTS"}).status_code == 409
    assert api.patch(f"/projects/{pid}", json={"name": "ornaments"}).json()["name"] == "ornaments"  # its own, recased
    assert api.patch("/projects/999", json={"name": "Nope"}).status_code == 404
    assert api.delete("/projects/999", params={"confirm": "true"}).status_code == 404
