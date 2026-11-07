from __future__ import annotations

import os
import stat
import subprocess

import pytest

from app import config, mounts, storage
from app.mounts import MountError, ShareSpec

from .conftest import posix_only


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "storage").mkdir(parents=True)
    monkeypatch.setattr(config.settings, "storage_root", str(data / "storage"))
    monkeypatch.setattr(config.settings, "storage_browse_root", str(data))
    # these tests are about the commands, not about whether this machine can really mount
    monkeypatch.setattr(mounts, "mount_capability", lambda *a, **k: {"ok": True, "smb": True, "nfs": True, "message": None, "smb_message": None, "nfs_message": None})
    storage.reset()
    yield data
    storage.reset()


class FakeMount:
    """Stands in for mount.run; records calls and can look at the world while a mount is 'running'."""

    def __init__(self, returncode=0, stderr="", raises=None, during=None):
        self.returncode, self.stderr, self.raises, self.during = returncode, stderr, raises, during
        self.calls = []

    def __call__(self, argv, timeout=30):
        self.calls.append(list(argv))
        if self.during:
            self.during(argv)
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


SMB = dict(protocol="smb", server="10.0.0.5", share="farmhand", username="alice", password="s3cret!", domain="HOME", version="3.0")


# ---------------------------------------------------------------- validation


def test_smb_fields_are_accepted_and_normalised():
    spec = mounts.validate_fields(**SMB)
    assert spec == ShareSpec("smb", "10.0.0.5", "farmhand", "alice", "s3cret!", "HOME", "3.0")
    assert mounts.validate_fields("smb", "nas.local", "/farmhand/Projects/stl/").share == "farmhand/Projects/stl"
    assert mounts.validate_fields("smb", "nas", "farmhand").version is None  # automatic


def test_nfs_fields_are_normalised_and_have_no_login():
    spec = mounts.validate_fields("nfs", "10.0.0.5", "volume1/farmhand", username="x", password="y", domain="z")
    assert spec == ShareSpec("nfs", "10.0.0.5", "/volume1/farmhand", None, None, None, "4")
    assert mounts.validate_fields("nfs", "nas", "/vol", version="3").version == "3"


def test_hostile_or_malformed_input_is_rejected():
    bad = [
        dict(protocol="ftp", server="nas", share="x"),
        dict(protocol="smb", server="-o evil", share="x"),  # would look like an option
        dict(protocol="smb", server="nas; reboot", share="x"),
        dict(protocol="smb", server="nas/evil", share="x"),
        dict(protocol="smb", server="", share="x"),
        dict(protocol="smb", server="nas", share=""),
        dict(protocol="smb", server="nas", share="../etc"),
        dict(protocol="smb", server="nas", share="a//b"),
        dict(protocol="smb", server="nas", share="a\\b"),
        dict(protocol="smb", server="nas", share="a,b"),
        dict(protocol="smb", server="nas", share="x", username="bob\nroot"),
        dict(protocol="smb", server="nas", share="x", username="bob", password="a\nb"),
        dict(protocol="smb", server="nas", share="x", username="bob", domain="bad domain!"),
        dict(protocol="smb", server="nas", share="x", version="9.9"),
        dict(protocol="nfs", server="nas", share="/a/../b"),
        dict(protocol="nfs", server="nas", share="/a:b"),
        dict(protocol="nfs", server="nas", share="/a", version="2"),
    ]
    for kwargs in bad:
        with pytest.raises(ValueError):
            mounts.validate_fields(**kwargs)


def test_names_and_mount_points(isolated):
    assert mounts.validate_name("  Lab NAS ") == "Lab NAS"
    for bad in ("", "../x", "a/b", "-x", "x" * 41):
        with pytest.raises(ValueError):
            mounts.validate_name(bad)
    assert mounts.slug("Lab NAS (2)") == "lab-nas-2"
    assert mounts.mount_point_for("Lab NAS") == (isolated / "nas" / "lab-nas").resolve()
    assert mounts.scratch_mount_point(7).name == ".test-7"  # hidden from the folder picker


# ---------------------------------------------------------------- one pasted location


def test_every_common_way_of_writing_a_location_is_understood():
    cases = [
        ("//192.168.1.50/farmhand", ("smb", "192.168.1.50", "farmhand")),
        ("//192.168.1.50/farmhand/Projects/stl/", ("smb", "192.168.1.50", "farmhand/Projects/stl")),
        ("\\\\nas\\farmhand\\Projects", ("smb", "nas", "farmhand/Projects")),  # Windows style
        ("smb://nas.local/farmhand", ("smb", "nas.local", "farmhand")),
        ("SMB://NAS.local/farmhand", ("smb", "NAS.local", "farmhand")),  # scheme isn't case-sensitive
        ("cifs://nas/farmhand/x", ("smb", "nas", "farmhand/x")),
        ("192.168.1.50:/volume1/farmhand", ("nfs", "192.168.1.50", "/volume1/farmhand")),
        ("nas.local:/volume1/farmhand/", ("nfs", "nas.local", "/volume1/farmhand")),
        ("nfs://nas/volume1/farmhand", ("nfs", "nas", "/volume1/farmhand")),
        ("nfs://nas:/volume1/farmhand", ("nfs", "nas", "/volume1/farmhand")),
        ("nas/farmhand", ("smb", "nas", "farmhand")),  # no prefix: assumed SMB
        ("   //nas/x   ", ("smb", "nas", "x")),
    ]
    for text, expected in cases:
        assert mounts.parse_location(text) == expected, text


def test_incomplete_or_unusable_locations_say_what_is_missing():
    wanted = [
        ("", "full address"),
        ("   ", "full address"),
        (None, "full address"),
        ("//nas", "share name"),
        ("//nas/", "share name"),
        ("nas", "share name"),
        ("192.168.1.50:", "export path"),
        ("nas:/", "export path"),
        ("nfs://nas", "export path"),
        ("ftp://nas/x", "doesn't look like a NAS address"),
    ]
    for text, message in wanted:
        with pytest.raises(ValueError, match=message):
            mounts.parse_location(text)


def test_a_login_is_refused_in_the_address():
    for text in ("smb://bob:hunter2@nas/share", "//bob@nas/share", "bob@nas:/vol", "nfs://bob@nas/vol"):
        with pytest.raises(ValueError, match="username and password out of the address"):
            mounts.parse_location(text)


def test_whatever_is_pasted_still_goes_through_the_normal_checks():
    # parse_location only splits; the same strict validation applies to the pieces afterwards
    for text in ("//-o evil/share", "//nas/../etc", "//nas; reboot/share", "nfs://nas/a/../b", "nas:/a:b"):
        with pytest.raises(ValueError):
            mounts.validate_fields(*mounts.parse_location(text))
    spec = mounts.validate_fields(*mounts.parse_location("//10.0.0.5/farmhand/Projects"), username="alice", password="x")
    assert (spec.protocol, spec.server, spec.share) == ("smb", "10.0.0.5", "farmhand/Projects")
    assert mounts.validate_fields(*mounts.parse_location("10.0.0.5:/volume1/x")).version == "4"


# ---------------------------------------------------------------- commands


def test_smb_command_uses_a_credentials_file_never_the_password():
    spec = mounts.validate_fields(**SMB)
    argv = mounts.build_mount_command(spec, "/data/nas/x", "/dev/shm/cred")
    assert argv[:5] == ["mount", "-t", "cifs", "//10.0.0.5/farmhand", "/data/nas/x"]
    opts = argv[argv.index("-o") + 1].split(",")
    assert "credentials=/dev/shm/cred" in opts and "vers=3.0" in opts and "uid=0" in opts
    assert not any("s3cret" in a for a in argv)


def test_smb_guest_and_automatic_version():
    argv = mounts.build_mount_command(mounts.validate_fields("smb", "nas", "pub"), "/m", None)
    opts = argv[argv.index("-o") + 1].split(",")
    assert "guest" in opts and not any(o.startswith(("vers=", "credentials=")) for o in opts)


def test_nfs_commands():
    v4 = mounts.build_mount_command(mounts.validate_fields("nfs", "nas", "/vol"), "/m")
    assert v4[:5] == ["mount", "-t", "nfs", "nas:/vol", "/m"]
    o4 = v4[v4.index("-o") + 1].split(",")
    assert "vers=4" in o4 and "soft" in o4 and "nolock" not in o4
    o3 = mounts.build_mount_command(mounts.validate_fields("nfs", "nas", "/vol", version="3"), "/m")
    assert "nolock" in o3[o3.index("-o") + 1].split(",")


def test_the_device_argument_can_never_look_like_an_option():
    for spec in (mounts.validate_fields("smb", "nas", "x"), mounts.validate_fields("nfs", "nas", "/x")):
        argv = mounts.build_mount_command(spec, "/m")
        assert not argv[3].startswith("-")


# ---------------------------------------------------------------- running mount


@posix_only  # 0o600 file permissions
def test_credentials_file_is_private_holds_the_login_and_is_removed(isolated, monkeypatch):
    seen = {}

    def during(argv):
        path = next(o.split("=", 1)[1] for o in argv[argv.index("-o") + 1].split(",") if o.startswith("credentials="))
        seen["mode"] = stat.S_IMODE(os.stat(path).st_mode)
        seen["content"] = open(path).read()
        seen["path"] = path
        seen["argv"] = " ".join(argv)

    fake = FakeMount(during=during)
    monkeypatch.setattr(mounts, "_run", fake)
    monkeypatch.setattr(mounts, "is_mounted", lambda p: False)

    mounts.mount(mounts.validate_fields(**SMB), isolated / "nas" / "lab")

    assert seen["mode"] == 0o600
    assert seen["content"] == "username=alice\npassword=s3cret!\ndomain=HOME\n"
    assert "s3cret" not in seen["argv"]
    assert not os.path.exists(seen["path"])  # gone as soon as the mount call finished
    assert (isolated / "nas" / "lab").is_dir()  # mount point created


def test_a_password_with_commas_survives_and_is_not_in_the_option_string(isolated, monkeypatch):
    seen = {}
    fake = FakeMount(during=lambda argv: seen.update(
        content=open(next(o.split("=", 1)[1] for o in argv[argv.index("-o") + 1].split(",") if o.startswith("credentials="))).read(),
        argv=" ".join(argv)))
    monkeypatch.setattr(mounts, "_run", fake)
    monkeypatch.setattr(mounts, "is_mounted", lambda p: False)
    spec = mounts.validate_fields("smb", "nas", "x", username="bob", password="pa,ss=wo,rd")
    mounts.mount(spec, isolated / "nas" / "x")
    assert "password=pa,ss=wo,rd\n" in seen["content"]
    assert "pa,ss" not in seen["argv"]


def test_the_credentials_file_is_removed_even_when_mounting_fails(isolated, monkeypatch):
    paths = []
    fake = FakeMount(returncode=32, stderr="mount error(13): Permission denied",
                     during=lambda argv: paths.append(next(o.split("=", 1)[1] for o in argv[argv.index("-o") + 1].split(",") if o.startswith("credentials="))))
    monkeypatch.setattr(mounts, "_run", fake)
    monkeypatch.setattr(mounts, "is_mounted", lambda p: False)
    with pytest.raises(MountError) as e:
        mounts.mount(mounts.validate_fields(**SMB), isolated / "nas" / "x")
    assert e.value.kind == "auth"
    assert paths and not os.path.exists(paths[0])


def test_already_mounted_is_a_no_op(isolated, monkeypatch):
    fake = FakeMount()
    monkeypatch.setattr(mounts, "_run", fake)
    monkeypatch.setattr(mounts, "is_mounted", lambda p: True)
    mounts.mount(mounts.validate_fields(**SMB), isolated / "nas" / "x")
    assert fake.calls == []


def test_a_timeout_becomes_a_clear_message(isolated, monkeypatch):
    monkeypatch.setattr(mounts, "_run", FakeMount(raises=subprocess.TimeoutExpired("mount", 30)))
    monkeypatch.setattr(mounts, "is_mounted", lambda p: False)
    with pytest.raises(MountError, match="Timed out") as e:
        mounts.mount(mounts.validate_fields("nfs", "10.0.0.5", "/vol"), isolated / "nas" / "x")
    assert e.value.kind == "unreachable"


def test_mounting_is_refused_with_instructions_when_the_container_lacks_permission(isolated, monkeypatch):
    monkeypatch.setattr(mounts, "mount_capability", lambda *a, **k: {"ok": False, "smb": False, "nfs": False, "message": "add SYS_ADMIN please", "smb_message": "add SYS_ADMIN please", "nfs_message": "add SYS_ADMIN please"})
    monkeypatch.setattr(mounts, "is_mounted", lambda p: False)
    fake = FakeMount()
    monkeypatch.setattr(mounts, "_run", fake)
    with pytest.raises(MountError, match="SYS_ADMIN") as e:
        mounts.mount(mounts.validate_fields(**SMB), isolated / "nas" / "x")
    assert e.value.kind == "privilege" and fake.calls == []


# ---------------------------------------------------------------- reading mount's errors


def test_mount_errors_are_translated_for_humans():
    smb = mounts.validate_fields("smb", "10.0.0.5", "farmhand", "u", "pw123456")
    nfs = mounts.validate_fields("nfs", "10.0.0.5", "/vol")
    cases = [
        (smb, "mount error(13): Permission denied", "auth"),
        (smb, "mount error(1): Operation not permitted", "privilege"),
        (smb, "mount error(2): No such file or directory", "not_found"),
        (smb, "mount error(113): No route to host", "unreachable"),
        (smb, "mount error(110): Connection timed out", "unreachable"),
        (smb, "mount error: could not resolve address for nas.local: Unknown error", "unreachable"),
        (smb, "mount: unknown filesystem type 'cifs'", "unsupported"),
        (smb, "mount error(95): Operation not supported", "version"),
        (nfs, "mount.nfs: access denied by server while mounting 10.0.0.5:/vol", "permission"),
        (nfs, "mount.nfs: mounting 10.0.0.5:/vol failed, reason given by server: No such file or directory", "not_found"),
        (nfs, "mount.nfs: Connection refused", "unreachable"),
        (smb, "something nobody has seen before", "other"),
    ]
    for spec, stderr, kind in cases:
        err = mounts.friendly_error(stderr, spec, allowed=False)
        assert err.kind == kind, f"{stderr!r} -> {err.kind}: {err}"
        assert len(str(err)) > 20  # a sentence, not a bare code


def test_operation_not_permitted_is_the_nas_saying_no_when_the_container_may_mount():
    smb = mounts.validate_fields("smb", "10.0.0.5", "farmhand", "elves", "pw123456")
    guest = mounts.validate_fields("smb", "10.0.0.5", "farmhand")
    nfs = mounts.validate_fields("nfs", "10.0.0.5", "/vol")
    err = mounts.friendly_error("mount error(1): Operation not permitted", smb, allowed=True)
    assert err.kind == "auth" and "elves" in str(err) and "SMB version" in str(err) and "docker-compose" not in str(err)
    assert "guests" in str(mounts.friendly_error("mount error(1): Operation not permitted", guest, allowed=True))
    assert mounts.friendly_error("mount.nfs: Operation not permitted", nfs, allowed=True).kind == "permission"
    # without the permission it's still the container, and "only root" always is
    assert mounts.friendly_error("mount error(1): Operation not permitted", smb, allowed=False).kind == "privilege"
    assert mounts.friendly_error("mount: only root can do that", smb, allowed=True).kind == "privilege"


def test_a_refused_mount_says_what_the_nas_did(isolated, monkeypatch):
    fake = FakeMount(returncode=32, stderr="mount error(1): Operation not permitted")
    monkeypatch.setattr(mounts, "_run", fake)
    monkeypatch.setattr(mounts, "is_mounted", lambda p: False)
    spec = mounts.validate_fields("smb", "10.0.0.5", "farmhand", "elves", "pw123456")
    with pytest.raises(mounts.MountError) as e:
        mounts.mount(spec, isolated / "x")
    assert e.value.kind == "auth" and "docker-compose" not in str(e.value)


def test_error_text_never_leaks_the_password():
    spec = mounts.validate_fields("smb", "nas", "x", "bob", "hunter2hunter2")
    err = mounts.friendly_error("weird failure involving hunter2hunter2 somewhere", spec)
    assert "hunter2hunter2" not in str(err)


# ---------------------------------------------------------------- unmounting


def test_unmount(isolated, monkeypatch):
    fake = FakeMount()
    monkeypatch.setattr(mounts, "_run", fake)
    monkeypatch.setattr(mounts, "is_mounted", lambda p: False)
    mounts.unmount(isolated / "nas" / "x")
    assert fake.calls == []  # nothing mounted, nothing to do

    monkeypatch.setattr(mounts, "is_mounted", lambda p: True)
    mounts.unmount(isolated / "nas" / "x")
    assert fake.calls[-1][0] == "umount" and "-l" not in fake.calls[-1]
    mounts.unmount(isolated / "nas" / "x", lazy=True)
    assert fake.calls[-1][:2] == ["umount", "-l"]


def test_unmounting_a_busy_share_says_so(isolated, monkeypatch):
    monkeypatch.setattr(mounts, "_run", FakeMount(returncode=32, stderr="umount: /data/nas/x: target is busy."))
    monkeypatch.setattr(mounts, "is_mounted", lambda p: True)
    with pytest.raises(MountError, match="busy") as e:
        mounts.unmount(isolated / "nas" / "x")
    assert e.value.kind == "busy"


# ---------------------------------------------------------------- environment checks


def test_cap_sys_admin_detection(tmp_path):
    def status(capeff):
        p = tmp_path / "status"
        p.write_text(f"Name:\tx\nCapEff:\t{capeff}\nCapBnd:\tffffffffffffffff\n")
        return str(p)

    assert mounts._has_cap_sys_admin(status("0000000000200000"))  # bit 21 set
    assert mounts._has_cap_sys_admin(status("000001ffffffffff"))  # privileged
    assert not mounts._has_cap_sys_admin(status("00000000a80425fb"))  # Docker's default set: no SYS_ADMIN
    assert not mounts._has_cap_sys_admin(str(tmp_path / "missing"))
    (tmp_path / "junk").write_text("CapEff:\tnot-hex\n")
    assert not mounts._has_cap_sys_admin(str(tmp_path / "junk"))


def test_capability_message_points_at_the_fix(tmp_path, monkeypatch):
    monkeypatch.undo()  # use the real mount_capability for this one
    status = tmp_path / "status"
    status.write_text("CapEff:\t00000000a80425fb\n")
    cap = mounts.mount_capability(str(status))
    assert not cap["ok"] and "SYS_ADMIN" in cap["message"]


# ---------------------------------------------------------------- SMB needs a second permission


SYS_ADMIN_ONLY = "0000000000200000"  # CAP_SYS_ADMIN (bit 21) but not DAC_READ_SEARCH (bit 2): what Docker gives with `cap_add: [SYS_ADMIN]`
BOTH = "0000000000200004"  # SYS_ADMIN + DAC_READ_SEARCH: what `cap_add: [SYS_ADMIN, DAC_READ_SEARCH]` gives
DOCKER_DEFAULT = "00000000a80425fb"  # neither


def _status(tmp_path, capeff):
    p = tmp_path / "status"
    p.write_text(f"Name:\tx\nCapEff:\t{capeff}\n")
    return str(p)


def _tools_present(monkeypatch):
    monkeypatch.setattr(mounts.shutil, "which", lambda name: f"/sbin/{name}")


def test_smb_needs_dac_read_search_as_well_as_sys_admin(tmp_path, monkeypatch):
    monkeypatch.undo()
    _tools_present(monkeypatch)

    both = mounts.mount_capability(_status(tmp_path, BOTH))
    assert both["ok"] and both["smb"] and both["nfs"] and both["smb_message"] is None

    sys_only = mounts.mount_capability(_status(tmp_path, SYS_ADMIN_ONLY))
    assert sys_only["ok"] and sys_only["nfs"] and not sys_only["smb"]  # NFS still works; SMB doesn't
    assert "DAC_READ_SEARCH" in sys_only["smb_message"] and sys_only["nfs_message"] is None

    neither = mounts.mount_capability(_status(tmp_path, DOCKER_DEFAULT))
    assert not neither["ok"] and "SYS_ADMIN" in neither["message"] and "DAC_READ_SEARCH" in neither["message"]


def test_smb_is_refused_up_front_with_the_reason_but_nfs_still_mounts(isolated, tmp_path, monkeypatch):
    status = _status(tmp_path, SYS_ADMIN_ONLY)
    monkeypatch.undo()  # drop the always-OK stand-in so the REAL permission check runs
    real_capability = mounts.mount_capability
    monkeypatch.setattr(mounts, "mount_capability", lambda *a, **k: real_capability(status))
    _tools_present(monkeypatch)
    monkeypatch.setattr(mounts, "is_mounted", lambda p: False)
    fake = FakeMount()
    monkeypatch.setattr(mounts, "_run", fake)

    with pytest.raises(MountError, match="DAC_READ_SEARCH") as e:
        mounts.mount(mounts.validate_fields(**SMB), isolated / "nas" / "smb")
    assert e.value.kind == "privilege" and fake.calls == []  # never got as far as running mount.cifs

    mounts.mount(mounts.validate_fields("nfs", "10.0.0.5", "/vol"), isolated / "nas" / "nfs")
    assert fake.calls and fake.calls[0][:3] == ["mount", "-t", "nfs"]


def test_a_missing_tool_is_reported_as_missing_not_as_a_permission_problem(isolated, tmp_path, monkeypatch):
    status = _status(tmp_path, BOTH)
    monkeypatch.undo()  # drop the always-OK stand-in so the REAL permission check runs
    real_capability = mounts.mount_capability
    monkeypatch.setattr(mounts, "mount_capability", lambda *a, **k: real_capability(status))
    monkeypatch.setattr(mounts.shutil, "which", lambda name: None if name == "mount.cifs" else f"/sbin/{name}")
    monkeypatch.setattr(mounts, "is_mounted", lambda p: False)
    monkeypatch.setattr(mounts, "_run", FakeMount())  # never run a real mount from a test
    with pytest.raises(MountError, match="cifs-utils") as e:
        mounts.mount(mounts.validate_fields(**SMB), isolated / "nas" / "x")
    assert e.value.kind == "unsupported"


def test_the_exact_error_mount_cifs_gives_without_the_second_permission_is_explained():
    spec = mounts.validate_fields(**SMB)
    err = mounts.friendly_error("Unable to apply new capability set.", spec)
    assert err.kind == "privilege"
    assert "DAC_READ_SEARCH" in str(err) and "SYS_ADMIN" in str(err) and "docker compose up -d" in str(err)


# ---------------------------------------------------------------- last-error memory


def test_last_error_registry():
    mounts.set_error(5, "auth", "wrong password")
    assert mounts.get_error(5) == ("auth", "wrong password")
    mounts.clear_error(5)
    assert mounts.get_error(5) is None
    mounts.clear_error(5)  # clearing nothing is fine
