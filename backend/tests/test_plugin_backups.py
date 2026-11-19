"""
A plugin's own copy of its settings, kept with Farmhand's (stream:backup): sent through the plugin API with its token,
kept by the plugin's id (removing and adding it again keeps it), written to the settings folder and read back from it,
and given back to the plugin from the Plugins page. And a plugin updated where it runs that asks for a new permission:
allowed on the Plugins page, its token kept.
"""
from __future__ import annotations

import json

import pytest

from app.services.plugins import backups, health, registry

from .factories import api_db
from .fake_plugin import MANIFEST
from .test_plugins import ADDRESS, add, bearer, from_ip, plugin  # noqa: F401 - (the fixture)

BACKUP_MANIFEST = {**MANIFEST, "permissions": [*MANIFEST["permissions"], "stream:backup"],
                   "backup": {"restore": "/api/farmhand-backup/restore"}}
PLUGIN_IP = "192.168.10.215"  # (it takes its token only from its own address)
COPY = {"format": 1, "saved_at": "2026-11-19T10:00:00+00:00",
        "settings": {"live_stream_key": "the-secret-key", "live_stream": "{\"cols\": 2}"}}


@pytest.fixture()
def backing_up(plugin):  # noqa: F811
    plugin.manifest = dict(BACKUP_MANIFEST)
    return plugin


def test_a_plugin_keeps_a_copy_of_its_settings_with_farmhand(api, backing_up):
    token = add(api, permissions=["printers:read", "stream:backup"])["token"]
    assert from_ip(api, PLUGIN_IP).get("/plugin-api/v1/backup", headers=bearer(token)).status_code == 404  # none yet
    r = from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps(COPY))
    assert r.status_code == 200 and r.json() == {"saved_at": COPY["saved_at"]}
    assert from_ip(api, PLUGIN_IP).get("/plugin-api/v1/backup", headers=bearer(token)).json() == COPY

    listed = api.get("/plugins").json()["plugins"][0]
    assert listed["backup"]["saved_at"] == COPY["saved_at"] and listed["can_restore"] is True
    assert "the-secret-key" not in json.dumps(listed)  # (the Plugins page never shows what's in it)

    # a newer one takes its place; one that isn't one is refused
    newer = {**COPY, "saved_at": "2026-11-19T11:00:00+00:00", "settings": {"live_stream_key": "another"}}
    from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps(newer))
    assert from_ip(api, PLUGIN_IP).get("/plugin-api/v1/backup", headers=bearer(token)).json()["settings"] == {"live_stream_key": "another"}
    assert from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps({"format": 2})).status_code == 422
    assert from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token),
                   content=json.dumps({**COPY, "settings": {"n": 1}})).status_code == 422
    big = {**COPY, "settings": {"x": "y" * (backups.MOST + 100 * 1024)}}
    assert from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps(big)).status_code == 413

    # removed and added again (a new token): its copy is still here, ready to be given back
    api.delete("/plugins/hello?confirm=true")
    token = add(api, permissions=["printers:read", "stream:backup"])["token"]
    assert from_ip(api, PLUGIN_IP).get("/plugin-api/v1/backup", headers=bearer(token)).json()["settings"] == {"live_stream_key": "another"}


def test_only_a_plugin_given_stream_backup_may_keep_one(api, backing_up):
    token = add(api, permissions=["printers:read"])["token"]
    r = from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps(COPY))
    assert r.status_code == 403 and "stream:backup" in r.json()["detail"]
    assert from_ip(api, PLUGIN_IP).get("/plugin-api/v1/backup", headers=bearer(token)).status_code == 403


def test_the_copies_go_to_the_settings_folder_and_come_back_from_it(api, backing_up, tmp_path):
    token = add(api, permissions=["printers:read", "stream:backup"])["token"]
    from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps(COPY))
    db = api_db(api)
    backups.write_all(db, tmp_path)
    written = json.loads((tmp_path / backups.FOLDER / "hello.json").read_text(encoding="utf-8"))
    assert written["plugin_id"] == "hello" and written["settings"] == COPY["settings"]
    stamp = (tmp_path / backups.FOLDER / "hello.json").stat().st_mtime_ns
    backups.write_all(db, tmp_path)
    assert (tmp_path / backups.FOLDER / "hello.json").stat().st_mtime_ns == stamp  # (unchanged: not written again)

    # a new Farmhand (none of its own): taken in; an older one in the folder never replaces a newer one here
    from app.models import PluginBackup

    db.delete(db.get(PluginBackup, "hello"))
    db.commit()
    assert backups.read_all(db, tmp_path) == ["hello"]
    assert backups.get(db, "hello")["settings"] == COPY["settings"]
    from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps({**COPY, "saved_at": "2026-11-20T00:00:00+00:00"}))
    assert backups.read_all(db, tmp_path) == []
    (tmp_path / backups.FOLDER / "other.json").write_text(json.dumps({**written, "plugin_id": "hello"}))  # (misnamed: left)
    assert backups.read_all(db, tmp_path) == []


def test_restoring_asks_the_plugin_to_take_its_settings_back(api, backing_up):
    token = add(api, permissions=["printers:read", "stream:backup"])["token"]
    assert api.post("/plugins/hello/backup/restore?confirm=true").status_code == 404  # no copy yet
    from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps(COPY))
    assert api.post("/plugins/hello/backup/restore").status_code == 409  # replaces its settings: needs confirm=true
    r = api.post("/plugins/hello/backup/restore?confirm=true")
    assert r.status_code == 200 and r.json() == {"restored": True, "saved_at": COPY["saved_at"], "note": "Restored."}
    asked = [q for q in backing_up.requests if q.url.path == "/api/farmhand-backup/restore"][-1]
    assert json.loads(asked.content) == {"saved_at": COPY["saved_at"]}  # (nothing secret in it: the plugin fetches it)

    backing_up.restore_answer = (403, {"detail": "This plugin wasn't given stream:backup."})
    r = api.post("/plugins/hello/backup/restore?confirm=true")
    assert r.status_code == 422 and r.json()["detail"] == "This plugin wasn't given stream:backup."
    backing_up.down = True
    assert "nothing answered there" in api.post("/plugins/hello/backup/restore?confirm=true").json()["detail"]


def test_a_plugin_asking_for_a_new_permission_is_allowed_on_the_plugins_page_keeping_its_token(api, plugin):  # noqa: F811
    token = add(api)["token"]  # (an older version of it: no stream:backup)
    plugin.manifest = {**BACKUP_MANIFEST, "version": "0.2.0"}
    db = api_db(api)
    health.check_all(db)
    listed = api.get("/plugins").json()["plugins"][0]
    assert [a["permission"] for a in listed["asks"]] == ["stream:backup"] and "stream key" in listed["asks"][0]["means"]
    assert listed["version"] == "0.1.0" and listed["can_restore"] is False  # (its newer manifest not taken yet)
    assert from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps(COPY)).status_code == 403

    r = api.post("/plugins/hello/allow")
    assert r.status_code == 200 and "stream:backup" in r.json()["permissions"] and r.json()["asks"] == []
    assert r.json()["version"] == "0.2.0" and r.json()["can_restore"] is True
    assert from_ip(api, PLUGIN_IP).put("/plugin-api/v1/backup", headers=bearer(token), content=json.dumps(COPY)).status_code == 200  # same token
    assert api.post("/plugins/hello/allow").status_code == 422  # (asking for nothing new now)


def test_a_manifest_naming_backup_must_ask_for_stream_backup(api, plugin):  # noqa: F811
    plugin.manifest = {**MANIFEST, "backup": {"restore": "/api/farmhand-backup/restore"}}
    r = api.post("/plugins", json={"address": ADDRESS, "permissions": []})
    assert r.status_code == 422 and "stream:backup" in r.json()["detail"]
    assert registry  # (imported for the fixture's module)
