from __future__ import annotations

import os

import pytest

from app import config_store, mounts, storage
from app.models import NetworkShare
from app.mounts import MountError
from app.services import config_service, farm_cost
from app.services import network_shares_service as shares
from app.services import save_location_service as svc

from .test_network_shares import SMB, nas  # noqa: F401 - the fake NAS fixture


def _real(p) -> str:
    return os.path.realpath(str(p))


def test_a_new_address_connects_and_makes_every_folder(db_session, nas):
    out = svc.set_save_location(db_session, {"address": "//10.0.0.5/prints/Farmhand", "username": "alice", "password": "s3cret!"})
    row = db_session.query(NetworkShare).one()
    assert (row.name, row.share, row.username, row.password) == ("Farmhand", "prints/Farmhand", "alice", "s3cret!")
    base = mounts.mount_point_for("Farmhand")
    for name in ("STL", "3MF", "Projects", "Farm cost", "Farmhand Configs"):
        assert (base / name).is_dir()
    assert storage.custom_path("stl") == _real(base / "STL") and storage.custom_path("project") == _real(base / "Projects")
    assert farm_cost.location_info(db_session)["path"] == _real(base / "Farm cost")
    assert config_service.location_path(db_session) == _real(base / "Farmhand Configs")
    assert (base / "Farmhand Configs" / config_store.CONFIG_FILENAME).is_file()  # the settings copy written there
    assert out["address"] == "//10.0.0.5/prints/Farmhand" and out["config_choice"] is None
    assert out["folders"]["threemf"] == _real(base / "3MF")


def test_the_share_already_there_and_its_folders_are_reused(db_session, nas):
    shares.create_share(db_session, {**SMB, "name": "TrueNas"})
    base = mounts.mount_point_for("TrueNas")
    (base / "stl").mkdir()
    (base / "farm cost").mkdir()
    svc.set_save_location(db_session, {"address": "smb://10.0.0.5/farmhand"})
    assert db_session.query(NetworkShare).count() == 1  # no second share for the same place
    assert storage.custom_path("stl") == _real(base / "stl")  # its own capitals kept, not a second "STL"
    assert farm_cost.location_info(db_session)["path"] == _real(base / "farm cost")
    assert (base / "3MF").is_dir() and [n for n in os.listdir(base) if n.lower() == "stl"] == ["stl"]


def test_a_folder_inside_a_connected_share(db_session, nas):
    shares.create_share(db_session, {**SMB, "name": "Lab NAS"})
    svc.set_save_location(db_session, {"address": "//10.0.0.5/farmhand/Print farm"})
    inside = mounts.mount_point_for("Lab NAS") / "Print farm"
    assert db_session.query(NetworkShare).count() == 1
    assert storage.custom_path("threemf") == _real(inside / "3MF")


def test_settings_already_saved_there_are_never_replaced_without_asking(db_session, nas):
    shares.create_share(db_session, {**SMB, "name": "TrueNas"})
    configs = mounts.mount_point_for("TrueNas") / "Farmhand Configs"
    configs.mkdir()
    doc = config_store.build_document(config_store.normalize_config({"appearance": {"scheme": "violet"}}), None, None, [])
    config_store.write_document(configs, doc)
    out = svc.set_save_location(db_session, {"address": "//10.0.0.5/farmhand"})
    assert out["config_choice"]["file_exists"] and out["config_choice"]["path"] == _real(configs)
    assert config_service.location_path(db_session) is None  # not chosen until the person says what to do
    assert config_store.read_document(configs)["appearance"]["scheme"] == "violet"
    assert storage.custom_path("stl") is not None  # the file folders are still set up


def test_a_refused_login_changes_nothing(db_session, nas):
    nas.fail_with = MountError("The NAS refused the connection: wrong username or password.", "auth")
    with pytest.raises(ValueError, match="wrong username or password"):
        svc.set_save_location(db_session, {"address": "//10.0.0.5/prints", "username": "alice", "password": "nope"})
    assert db_session.query(NetworkShare).count() == 0 and storage.custom_path("stl") is None
    assert svc.describe(db_session)["address"] is None


def test_save_location_over_the_api(api, nas):
    r = api.put("/settings/storage/save-location", json={"address": "//10.0.0.5/prints"})
    assert r.status_code == 200, r.text
    assert api.get("/settings/storage/save-location").json()["address"] == "//10.0.0.5/prints"
    nas.fail_with = MountError("The NAS refused the connection.", "auth")
    r = api.put("/settings/storage/save-location", json={"address": "//10.0.0.9/other"})
    assert r.status_code == 422 and "refused" in r.json()["detail"]


def test_the_save_location_says_how_its_share_is_and_takes_its_version(db_session, nas):
    assert svc.describe(db_session)["share"] is None
    svc.set_save_location(db_session, {"address": "//10.0.0.5/prints/Farmhand", "username": "alice", "password": "s3cret!"})
    share = svc.describe(db_session)["share"]
    assert share["name"] == "Farmhand" and share["mounted"] and share["has_password"] and "password" not in share
    assert svc.describe(db_session)["capability"]["ok"]
    svc.set_save_location(db_session, {"address": "//10.0.0.5/prints/Farmhand", "username": "alice", "version": "3.0", "domain": "WORKGROUP"})
    row = db_session.query(NetworkShare).one()
    assert (row.version, row.domain, row.password) == ("3.0", "WORKGROUP", "s3cret!")  # the password kept
