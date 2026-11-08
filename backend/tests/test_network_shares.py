from __future__ import annotations

import io
from pathlib import Path

import pytest

from app import mounts
from app.models import NetworkShare, SourceFileType
from app.mounts import MountError
from app.services import network_shares_service as shares
from app.services import source_model_service
from app.services import storage_settings_service as storage_settings

from .conftest import posix_only

SMB = dict(name="Lab NAS", protocol="smb", server="10.0.0.5", share="farmhand", username="alice", password="s3cret!")


# ------------------------------------------------------------------ adding


@posix_only  # the mount point is a / path
def test_adding_a_share_mounts_it_saves_it_and_never_returns_the_password(db_session, nas):
    out = shares.create_share(db_session, SMB)

    assert out["mounted"] and out["name"] == "Lab NAS"
    assert out["address"] == "smb://10.0.0.5/farmhand"
    assert out["mount_point"].endswith("/nas/lab-nas")
    assert out["has_password"] is True and "password" not in out
    assert db_session.get(NetworkShare, out["id"]).password == "s3cret!"  # kept so it can be re-mounted later
    assert shares.list_shares(db_session)["shares"][0]["id"] == out["id"]


def test_a_connection_that_fails_saves_nothing(db_session, nas):
    nas.fail_with = MountError("The NAS refused the connection: wrong username or password.", "auth")
    with pytest.raises(MountError, match="refused"):
        shares.create_share(db_session, SMB)
    assert shares.list_shares(db_session)["shares"] == []


def test_invalid_input_is_rejected_before_anything_is_mounted(db_session, nas):
    for bad in (dict(SMB, server="-o evil"), dict(SMB, share="../x"), dict(SMB, name=""), dict(SMB, protocol="ftp")):
        with pytest.raises(ValueError):
            shares.create_share(db_session, bad)
    assert nas.mount_calls == []


def test_names_that_would_share_a_mount_point_are_refused(db_session, nas):
    shares.create_share(db_session, SMB)
    with pytest.raises(ValueError, match="already a share called"):
        shares.create_share(db_session, dict(SMB, name="lab nas"))  # same folder name once tidied


def test_one_pasted_location_is_enough(db_session, nas):
    out = shares.create_share(
        db_session, dict(name="Lab NAS", location="//10.0.0.5/farmhand/Projects", username="alice", password="s3cret!")
    )
    row = db_session.get(NetworkShare, out["id"])
    assert (row.protocol, row.server, row.share) == ("smb", "10.0.0.5", "farmhand/Projects")
    assert out["address"] == "smb://10.0.0.5/farmhand/Projects"  # the same single line, ready to edit

    nfs = shares.create_share(db_session, dict(name="Backup", location="10.0.0.6:/volume1/farmhand"))
    row = db_session.get(NetworkShare, nfs["id"])
    assert (row.protocol, row.server, row.share, row.version) == ("nfs", "10.0.0.6", "/volume1/farmhand", "4")
    assert nfs["address"] == "10.0.0.6:/volume1/farmhand"


def test_the_address_shown_can_be_pasted_straight_back(db_session, nas):
    for name, location in (("A", "//10.0.0.5/farmhand/x"), ("B", "10.0.0.6:/volume1/y")):
        out = shares.create_share(db_session, dict(name=name, location=location))
        assert mounts.parse_location(out["address"]) == mounts.parse_location(location)


def test_a_bad_location_is_rejected_before_any_mount(db_session, nas):
    for bad in ("//10.0.0.5", "smb://bob:pw@10.0.0.5/farmhand", "ftp://x/y", "//-o evil/share"):
        with pytest.raises(ValueError):
            shares.create_share(db_session, dict(name="X", location=bad))
    assert nas.mount_calls == []


def test_editing_the_location_replaces_server_and_share_together(db_session, nas):
    out = shares.create_share(db_session, SMB)
    shares.update_share(db_session, out["id"], {"location": "//10.0.0.9/newshare/sub"})
    row = db_session.get(NetworkShare, out["id"])
    assert (row.server, row.share, row.password) == ("10.0.0.9", "newshare/sub", "s3cret!")


def test_an_existing_share_cannot_be_switched_to_the_other_protocol_by_editing(db_session, nas):
    out = shares.create_share(db_session, SMB)  # SMB
    with pytest.raises(ValueError, match="SMB share, but that address is NFS"):
        shares.update_share(db_session, out["id"], {"location": "10.0.0.5:/volume1/farmhand"})
    assert db_session.get(NetworkShare, out["id"]).protocol == "smb"


# ------------------------------------------------------------------ editing


def test_editing_without_a_password_keeps_the_saved_one(db_session, nas):
    out = shares.create_share(db_session, SMB)
    shares.update_share(db_session, out["id"], {"share": "farmhand/stl"})
    row = db_session.get(NetworkShare, out["id"])
    assert row.share == "farmhand/stl" and row.password == "s3cret!"


def test_new_settings_are_tried_on_a_scratch_mount_so_a_typo_cannot_break_a_working_share(db_session, nas):
    out = shares.create_share(db_session, SMB)
    nas.fail_scratch = MountError("The NAS refused the connection: wrong username or password.", "auth")

    with pytest.raises(MountError, match="refused"):
        shares.update_share(db_session, out["id"], {"password": "typo"})

    row = db_session.get(NetworkShare, out["id"])
    assert row.password == "s3cret!"  # unchanged
    assert nas.is_mounted(out["mount_point"])  # the live connection was never touched


def test_a_good_edit_replaces_the_connection(db_session, nas):
    out = shares.create_share(db_session, SMB)
    updated = shares.update_share(db_session, out["id"], {"password": "new-pass", "server": "10.0.0.9"})
    row = db_session.get(NetworkShare, out["id"])
    assert (row.server, row.password) == ("10.0.0.9", "new-pass")
    assert updated["mounted"] and nas.mount_calls[-1][0].server == "10.0.0.9"


def test_clearing_the_username_switches_to_guest_and_drops_the_password(db_session, nas):
    out = shares.create_share(db_session, SMB)
    shares.update_share(db_session, out["id"], {"username": ""})
    row = db_session.get(NetworkShare, out["id"])
    assert row.username is None and row.password is None


# ------------------------------------------------------------------ removing


def test_a_share_that_is_a_storage_location_cannot_be_removed(db_session, nas):
    out = shares.create_share(db_session, SMB)
    folder = Path(out["mount_point"]) / "stl"
    folder.mkdir()
    storage_settings.save(db_session, {"stl_path": str(folder)})

    with pytest.raises(shares.ShareInUse, match="STL files"):
        shares.delete_share(db_session, out["id"])
    assert nas.is_mounted(out["mount_point"])  # still connected

    storage_settings.save(db_session, {"stl_path": None})  # switch back to the default
    shares.delete_share(db_session, out["id"])
    assert not nas.is_mounted(out["mount_point"])
    assert shares.list_shares(db_session)["shares"] == []


def test_removing_an_unknown_share_is_a_clear_error(db_session, nas):
    with pytest.raises(shares.ShareNotFound):
        shares.delete_share(db_session, 999)


def test_files_stored_on_a_share_are_counted(db_session, nas):
    out = shares.create_share(db_session, SMB)
    folder = Path(out["mount_point"]) / "stl"
    folder.mkdir()
    storage_settings.save(db_session, {"stl_path": str(folder)})
    source_model_service.create_source_model(
        db_session, name="M.stl", file_type=SourceFileType.stl, file_obj=io.BytesIO(b"x" * 100)
    )
    assert shares.list_shares(db_session)["shares"][0]["files_here"] == 1


# ------------------------------------------------------------------ keeping shares mounted


def test_saved_shares_are_remounted_after_a_restart(db_session, nas):
    out = shares.create_share(db_session, SMB)
    nas.mounted.clear()  # a restart wipes the container's mounts
    assert not shares.list_shares(db_session)["shares"][0]["mounted"]

    shares.ensure_mounted(db_session)
    assert nas.is_mounted(out["mount_point"])


def test_a_nas_that_is_switched_on_later_is_picked_up_automatically(db_session, nas):
    out = shares.create_share(db_session, SMB)
    nas.mounted.clear()
    nas.fail_with = MountError("Couldn't reach 10.0.0.5.", "unreachable")

    shares.ensure_mounted(db_session)
    listed = shares.list_shares(db_session)["shares"][0]
    assert not listed["mounted"] and listed["error_kind"] == "unreachable"  # the reason is visible in the UI

    nas.fail_with = None  # the NAS finished booting
    shares.ensure_mounted(db_session)
    listed = shares.list_shares(db_session)["shares"][0]
    assert listed["mounted"] and listed["error"] is None
    assert nas.is_mounted(out["mount_point"])


def test_a_wrong_password_is_not_retried_automatically(db_session, nas):
    """Repeated bad logins can lock a NAS account, and retrying can't fix a wrong password anyway."""
    out = shares.create_share(db_session, SMB)
    nas.mounted.clear()
    nas.fail_with = MountError("wrong username or password", "auth")
    shares.ensure_mounted(db_session)  # one attempt, recorded as an auth failure
    attempts = len(nas.mount_calls)

    nas.fail_with = None
    shares.ensure_mounted(db_session)
    shares.ensure_mounted(db_session)
    assert len(nas.mount_calls) == attempts  # no more automatic attempts

    shares.reconnect_share(db_session, out["id"])  # the person pressing Reconnect does retry
    assert nas.is_mounted(out["mount_point"])
    assert shares.list_shares(db_session)["shares"][0]["error"] is None


def test_a_nas_folder_is_found_in_the_share_that_reaches_it():
    from app.models import NetworkShare
    from app.services.network_shares_service import folder_inside

    smb = NetworkShare(name="TrueNas", protocol="smb", server="192.168.4.20", share="3d_prints")
    assert folder_inside(smb, "smb", "192.168.4.20", "/3D_Prints/") == ""  # SMB ignores case and the slashes
    assert folder_inside(smb, "smb", "192.168.4.20", r"3d_prints\Farmhand\3MF") == "Farmhand/3MF"
    assert folder_inside(smb, "smb", "192.168.4.21", "3d_prints") is None  # another NAS
    assert folder_inside(smb, "nfs", "192.168.4.20", "3d_prints") is None
    assert folder_inside(smb, "smb", "192.168.4.20", "3d_prints_old") is None  # not inside it
    nfs = NetworkShare(name="Exports", protocol="nfs", server="nas", share="/mnt/tank/prints")
    assert folder_inside(nfs, "nfs", "NAS", "/mnt/tank/prints") == ""
    assert folder_inside(nfs, "nfs", "nas", "/mnt/tank/Prints") is None  # an NFS export is a path: case counts
