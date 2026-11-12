"""
The Plugins page's side of plugins: adding one by its address (its manifest fetched from there, shown, then added),
the plugin API taking a token only from the plugin's address and only so often, switching a plugin off, the health
check, the plugin's page passed on from wherever it runs, and the settings copy bringing plugins back without tokens.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.plugins import cache, health, limits, registry, remote

from .fake_plugin import MANIFEST, FakePlugin

ADDRESS = "http://192.168.10.215:8080"


@pytest.fixture()
def plugin(monkeypatch):
    """A plugin answering at ADDRESS, on another machine."""
    fake = FakePlugin(ADDRESS)
    monkeypatch.setattr(remote, "transport", httpx.MockTransport(fake.handle))
    cache.clear()
    limits.reset()
    remote.forget_resolved()
    yield fake
    limits.reset()
    remote.forget_resolved()


def from_ip(api: TestClient, ip: str) -> TestClient:
    """The same API, called from another machine on the network."""
    return TestClient(app, client=(ip, 40000))


def add(api, permissions=("printers:read", "farm:read"), **extra) -> dict:
    r = api.post("/plugins", json={"address": ADDRESS, "permissions": list(permissions), **extra})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ adding a plugin by its address


def test_looking_at_a_plugin_before_adding_it(api, plugin):
    r = api.post("/plugins/preview", json={"address": " 192.168.10.215:8080/ "})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["address"] == ADDRESS and body["installed"] is False
    assert body["manifest"]["id"] == "hello" and body["manifest"]["page"]["menu"] == "Hello"
    assert [p["permission"] for p in body["permissions_described"]] == ["printers:read", "farm:read"]
    assert body["permissions_described"][0]["means"].startswith("see your printers")
    assert api.get("/plugins").json()["plugins"] == []  # nothing added yet
    assert str(plugin.requests[-1].url) == f"{ADDRESS}/manifest"


@pytest.mark.parametrize("address, words", [
    ("", "Type the plugin's address"),
    ("ftp://192.168.10.215", "must start with http://"),
    ("http://user:pw@192.168.10.215", "can't have a password"),
    ("http://192.168.10.215:99999", "isn't an address Farmhand can use"),
    ("http://192.168.10.216:8080", "nothing answered there"),
    ("http://192.168.10.215:8080/nope", "/manifest got 404"),
])
def test_an_address_that_isnt_a_plugin_says_why(api, plugin, address, words):
    r = api.post("/plugins/preview", json={"address": address})
    assert r.status_code == 422 and words in r.json()["detail"], r.text


def test_a_plugin_with_a_bad_manifest_isnt_added(api, plugin):
    plugin.manifest["farmhand_api"] = "2"
    r = api.post("/plugins", json={"address": ADDRESS, "permissions": []})
    assert r.status_code == 422 and 'version "2"' in r.json()["detail"]
    plugin.manifest = "not json"
    assert "isn't a JSON object" in api.post("/plugins/preview", json={"address": ADDRESS}).json()["detail"]


def test_adding_by_address_shows_the_token_once(api, plugin):
    body = add(api)
    token, p = body["token"], body["plugin"]
    assert len(token) >= 40
    assert (p["id"], p["address"], p["only_from_address"], p["needs_token"]) == ("hello", ADDRESS, True, False)
    assert p["permissions"] == ["printers:read", "farm:read"] and p["page"] == {"menu": "Hello", "icon": None, "path": "/"}
    assert p["health"]["state"] == "running" and p["health"]["last_seen_at"]
    assert token not in api.get("/plugins").text
    # what the plugin asks for is fetched from it, never taken from the page: more than it asks can't be granted
    r = api.post("/plugins", json={"address": ADDRESS, "permissions": ["cameras:read"]})
    assert r.status_code == 409  # already added
    api.delete("/plugins/hello?confirm=true")
    r = api.post("/plugins", json={"address": ADDRESS, "permissions": ["cameras:read"]})
    assert r.status_code == 422 and "didn't ask for 'cameras:read'" in r.json()["detail"]
    assert api.post("/plugins/preview", json={"address": ADDRESS}).json()["installed"] is False


def test_moving_a_plugin_to_another_address(api, plugin):
    add(api)
    r = api.patch("/plugins/hello", json={"address": "http://192.168.10.99:8080"})
    assert r.status_code == 422 and "nothing answered" in r.json()["detail"]
    plugin.address = "http://192.168.10.99:8080"
    assert api.patch("/plugins/hello", json={"address": "192.168.10.99:8080"}).json()["address"] == plugin.address
    plugin.manifest["id"] = "other"
    r = api.patch("/plugins/hello", json={"address": plugin.address})
    assert r.status_code == 422 and 'is "other", not "hello"' in r.json()["detail"]


# ------------------------------------------------------------------ the plugin API across the network


def test_a_token_is_taken_only_from_the_plugins_address(api, plugin):
    token = add(api)["token"]
    there = from_ip(api, "192.168.10.215")
    assert there.get("/plugin-api/v1/me", headers=bearer(token)).status_code == 200
    assert from_ip(api, "::ffff:192.168.10.215").get("/plugin-api/v1/me", headers=bearer(token)).status_code == 200
    r = from_ip(api, "192.168.10.50").get("/plugin-api/v1/printers", headers=bearer(token))
    assert r.status_code == 403
    assert "only from its address, 192.168.10.215, and this call came from 192.168.10.50" in r.json()["detail"]
    # switched off on the Plugins page: from anywhere
    assert api.patch("/plugins/hello", json={"only_from_address": False}).json()["only_from_address"] is False
    assert from_ip(api, "192.168.10.50").get("/plugin-api/v1/me", headers=bearer(token)).status_code == 200


def test_a_plugin_beside_farmhand_is_known_by_its_container_name(api, plugin, monkeypatch):
    plugin.address = "http://hello:8080"
    token = api.post("/plugins", json={"address": "http://hello:8080", "permissions": []}).json()["token"]
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("172.18.0.7", 0))] if host == "hello" else [])
    assert from_ip(api, "172.18.0.7").get("/plugin-api/v1/me", headers=bearer(token)).status_code == 200
    assert from_ip(api, "172.18.0.8").get("/plugin-api/v1/me", headers=bearer(token)).status_code == 403


def test_a_plugin_asking_too_often_is_told_to_slow_down(api, plugin, monkeypatch):
    monkeypatch.setattr(limits, "BURST", 3)
    monkeypatch.setattr(limits, "RATE", 0.001)
    token = add(api)["token"]
    other = api.post("/plugins", json={"manifest": {**MANIFEST, "id": "other"}, "permissions": []}).json()["token"]
    there = from_ip(api, "192.168.10.215")
    assert [there.get("/plugin-api/v1/me", headers=bearer(token)).status_code for _ in range(4)] == [200, 200, 200, 429]
    r = there.get("/plugin-api/v1/me", headers=bearer(token))
    assert r.status_code == 429 and "asking Farmhand too often" in r.json()["detail"] and int(r.headers["Retry-After"]) >= 1
    assert api.get("/plugin-api/v1/me", headers=bearer(other)).status_code == 200  # each token has its own


# ------------------------------------------------------------------ switching off, a new token


def test_a_plugin_switched_off_has_its_token_refused_and_its_page_closed(api, plugin):
    token = add(api)["token"]
    there = from_ip(api, "192.168.10.215")
    r = api.patch("/plugins/hello", json={"enabled": False})
    assert r.json()["enabled"] is False and r.json()["health"]["state"] == "off"
    assert there.get("/plugin-api/v1/me", headers=bearer(token)).status_code == 401
    r = api.get("/plugins/hello/page/")
    assert r.status_code == 403 and "switched off" in r.text
    api.patch("/plugins/hello", json={"enabled": True})
    assert there.get("/plugin-api/v1/me", headers=bearer(token)).status_code == 200
    assert api.patch("/plugins/nothing", json={"enabled": False}).status_code == 404


# ------------------------------------------------------------------ health


def test_the_health_check_keeps_how_each_plugin_is_doing(db_session, plugin):
    p, _ = registry.register_by_address(db_session, ADDRESS, [])
    plugin.unwell = True
    health.check_all(db_session)
    h = registry.out(p)["health"]
    # it's running (it answered), and says what's wrong: its page is still shown
    assert h["state"] == "unwell" and h["last_error"] == "The plugin answered 503 to /health: the camera reader is stuck"
    seen = p.connection.last_seen_at
    plugin.unwell, plugin.down = False, True
    health.check_all(db_session)
    h = registry.out(p)["health"]
    assert h["state"] == "not_answering" and "nothing answered there" in h["last_error"] and h["checked_at"]
    assert registry.out(p)["health"]["last_seen_at"] == registry.out(p)["health"]["last_seen_at"]  # kept from before
    assert p.connection.last_seen_at == seen
    plugin.down = False
    health.check_all(db_session)
    assert registry.out(p)["health"]["state"] == "running" and registry.out(p)["health"]["last_error"] is None
    # one switched off isn't asked
    registry.update(db_session, "hello", enabled=False)
    plugin.requests.clear()
    health.check_all(db_session)
    assert plugin.requests == []


def test_a_plugin_renamed_where_it_runs_is_renamed_in_farmhand(db_session, plugin):
    p, _ = registry.register_by_address(db_session, ADDRESS, [])
    plugin.manifest = {**plugin.manifest, "name": "Hello there", "version": "0.2.0", "page": {"menu": "Hi", "path": "/"}}
    health.check_all(db_session)
    out = registry.out(p)
    assert (out["name"], out["version"], out["page"]["menu"]) == ("Hello there", "0.2.0", "Hi")
    # asking for a new permission needs the operator's yes: the manifest Farmhand has stays as it was
    plugin.manifest = {**plugin.manifest, "name": "Greedy", "permissions": [*plugin.manifest["permissions"], "prints:read"]}
    health.check_all(db_session)
    assert registry.out(p)["name"] == "Hello there"
    # nor is it taken while the plugin isn't well
    plugin.manifest, plugin.unwell = {**plugin.manifest, "name": "Sick", "permissions": MANIFEST["permissions"]}, True
    health.check_all(db_session)
    assert registry.out(p)["name"] == "Hello there"


def test_a_plugin_naming_no_health_path_is_asked_for_its_manifest(db_session, plugin):
    del plugin.manifest["health"]
    p, _ = registry.register_by_address(db_session, ADDRESS, [])
    plugin.requests.clear()
    assert health.check(db_session, p) is None
    assert str(plugin.requests[0].url) == f"{ADDRESS}/manifest"


def test_the_health_check_runs_in_the_background():
    from app import background

    assert health.worker.interval == 30 and isinstance(health.worker, background.PeriodicWorker)


# ------------------------------------------------------------------ the plugin's page inside Farmhand


def test_the_plugins_page_is_passed_on_from_where_it_runs(api, plugin):
    add(api)
    r = api.get("/plugins/hello/page/")
    assert r.status_code == 200 and r.text == "<h1>Hello from the plugin</h1>" and r.headers["x-plugin"] == "hello"
    assert r.headers["set-cookie"] == "a=1"
    r = api.post("/plugins/hello/page/echo?x=1&y=two", content=b"name=frog")
    assert r.json() == {"method": "POST", "query": "x=1&y=two", "body": "name=frog", "prefix": "/plugins/hello"}
    r = api.get("/plugins/hello/page/old", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/plugins/hello/new"
    r = api.get("/plugins/hello/page/events")
    assert r.headers["content-type"].startswith("text/event-stream") and r.text == "event: hi\ndata: 1\n\n"
    assert api.get("/plugins/hello/page/missing").status_code == 404


def test_a_plugin_that_isnt_running_says_so_in_its_page(api, plugin):
    add(api)
    plugin.down = True
    r = api.get("/plugins/hello/page/")
    assert r.status_code == 502 and "This plugin isn&#x27;t running" in r.text and "nothing answered there" in r.text
    r = api.get("/plugins/nothing/page/")
    assert r.status_code == 404 and "no such plugin" in r.text


def test_the_plugin_pages_script_is_served(api):
    r = api.get("/plugins/farmhand-plugin.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert "farmhand:theme" in r.text and "window.farmhand" in r.text


def test_looking_at_a_plugin_or_its_page_doesnt_rewrite_the_settings_copy():
    from app import change_hooks
    from app.services import config_service

    assert change_hooks._what_changed("/plugins/preview") is None
    assert change_hooks._what_changed("/plugins/hello/page/echo") is None
    assert change_hooks._what_changed("/plugins/hello") == config_service.MirrorScope()


# ------------------------------------------------------------------ the settings copy and Load all


def test_load_all_brings_plugins_back_needing_a_new_token(db_session, other_farmhand, share, plugin, api):
    from app.services import app_settings
    from app.services import config_service as svc

    svc.nas_copy._last_mirror.update(ok=None, error=None, at=None)
    p, token = registry.register_by_address(db_session, ADDRESS, ["printers:read"], only_from_address=False)
    registry.update(db_session, "hello", enabled=False)
    folder = share / "settings"
    folder.mkdir()
    svc.set_location(db_session, str(folder))
    written = json.loads((folder / "farmhand-config.json").read_text())
    assert written["plugins"][0]["address"] == ADDRESS and written["plugins"][0]["enabled"] is False
    assert token not in json.dumps(written) and registry.hash_token(token) not in json.dumps(written)

    db2 = other_farmhand
    app_settings.put(db2, svc.KEY_LOCATION, str(folder))
    db2.commit()
    out = svc.restore(db2)
    assert "plugins" in out["restored"] and out["plugins"] == {"added": ["Hello"], "kept": []}
    assert any("make a new token for each" in w for w in out["warnings"])
    back = registry.out(registry.get(db2, "hello"))
    assert (back["address"], back["only_from_address"], back["enabled"], back["permissions"]) == (ADDRESS, False, False, ["printers:read"])
    assert back["needs_token"] is True and back["token_created_at"] is None
    assert registry.caller(db2, token) is None  # the old token isn't brought back
    registry.new_token(db2, "hello")
    assert registry.out(registry.get(db2, "hello"))["needs_token"] is False
    # Load all again: what's here is kept as it is
    again = svc.restore(db2)
    assert again["plugins"] == {"added": [], "kept": ["Hello"]} and "plugins" not in again["restored"]


def test_a_damaged_plugin_entry_is_left_out_saying_why(db_session):
    out = registry.restore_entries(db_session, [{"id": "x", "name": "X", "manifest": {"id": "x"}}])
    assert out["added"] == [] and "The plugin “X” wasn't put back" in out["warnings"][0]
