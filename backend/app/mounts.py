"""
Mounting NAS shares (SMB/CIFS and NFS) from inside the app, so the whole thing can be
set up from the web interface instead of by editing files on the host.

What this needs from the environment (docker-compose.yml provides both):
  * the container must be allowed to mount: the SYS_ADMIN capability — and, for SMB, DAC_READ_SEARCH too
  * the image must have the client tools: mount.cifs (cifs-utils) and mount.nfs (nfs-common)

Mounts live in the container's own mount namespace: they disappear when the container
restarts, so saved shares are re-mounted at startup and kept mounted by a supervisor
(see mount_supervisor.py).

Everything a person types ends up in a subprocess command, so:
  * every field is validated against a strict pattern first,
  * commands are argument lists, never a shell string,
  * an SMB password is passed in a temporary 0600 credentials file — never on the command
    line, where `ps` would show it, and never inside a comma-separated option string, where
    a comma in the password would break parsing.

Nothing here has been run against a real NAS in the environment this was written in; the
commands it builds and the way it reads mount's error output are covered by tests that use
a fake `mount`.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import storage

log = logging.getLogger("farmhand.mounts")

PROTOCOLS = ("smb", "nfs")
SMB_VERSIONS = ("", "3.1.1", "3.0", "2.1")  # "" = let the kernel negotiate
NFS_VERSIONS = ("4", "3")
MOUNT_TIMEOUT_SECONDS = 30
CAP_SYS_ADMIN_BIT = 21
CAP_DAC_READ_SEARCH_BIT = 2  # mount.cifs refuses to run without it, on top of SYS_ADMIN


class MountError(ValueError):
    """Mounting/unmounting failed. The message is written to be shown to the person using the app."""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind  # auth | permission | not_found | unreachable | privilege | unsupported | version | busy | other


@dataclass(frozen=True)
class ShareSpec:
    protocol: str
    server: str
    share: str  # SMB: share[/sub/path]   NFS: the export path, e.g. /volume1/farmhand
    username: str | None = None
    password: str | None = None
    domain: str | None = None
    version: str | None = None


# ------------------------------------------------------------------ validation

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$")
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_DOMAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SMB_BAD = re.compile(r'[\\:*?"<>|,\x00-\x1f]')
_NFS_PATH = re.compile(r"^/[A-Za-z0-9 ._+@/-]*$")
_CONTROL = re.compile(r"[\x00-\x1f]")


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-.")
    return s or "share"


def mount_point_for(name: str) -> Path:
    """Where a share is mounted inside the container — under the folder picker's reach."""
    return storage.browse_root() / "nas" / slug(name)


def scratch_mount_point(share_id: int) -> Path:
    """A temporary mount point (hidden from the picker) for trying new settings without touching a live mount."""
    return storage.browse_root() / "nas" / f".test-{share_id}"


def validate_name(name: str | None) -> str:
    name = (name or "").strip()
    if not _NAME.match(name):
        raise ValueError(
            "Give the share a short name (letters, numbers, spaces, . _ -) — it's how you'll recognise it in Farmhand."
        )
    return name


_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$")
_LOCATION_HELP = (
    "Enter the full address of the folder on your NAS, like //192.168.1.50/farmhand "
    "(SMB) or 192.168.1.50:/volume1/farmhand (NFS)."
)
_NO_LOGIN_IN_ADDRESS = "Leave the username and password out of the address — enter them in the fields below."


def parse_location(text: str | None) -> tuple[str, str, str]:
    r"""
    Split ONE pasted NAS location into (protocol, server, share) so people don't have to.
    Accepts the forms people actually copy:

        //192.168.1.50/farmhand/Projects        SMB, Linux/Mac style
        \\nas\farmhand\Projects                SMB, Windows style
        smb://nas.local/farmhand  (or cifs://)  SMB, as a URL
        192.168.1.50:/volume1/farmhand          NFS, as NAS screens show it
        nfs://nas/volume1/farmhand              NFS, as a URL
        nas/farmhand                            no prefix: assumed SMB

    For SMB the first folder is the share and anything after it is a sub-folder of it.
    Returns the raw pieces; validate_fields() still checks them. Logins aren't accepted in
    the address (they'd end up in places a password shouldn't).
    """
    raw = (text or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError(_LOCATION_HELP)

    m = _SCHEME.match(raw)
    if m:
        scheme = m.group(1).lower()
        if scheme in ("smb", "cifs"):
            protocol, rest = "smb", m.group(2)
        elif scheme == "nfs":
            protocol, rest = "nfs", m.group(2)
        else:
            raise ValueError(
                "That doesn't look like a NAS address. Use //server/share (SMB) or server:/export (NFS), "
                "or an smb:// or nfs:// address."
            )
    elif raw.startswith("//"):
        protocol, rest = "smb", raw[2:]
    elif re.match(r"^[^/]*:", raw):  # "host:/path" — a colon before any slash
        protocol, rest = "nfs", raw
    else:
        protocol, rest = "smb", raw

    head, _, tail = rest.lstrip("/").partition("/")
    if protocol == "nfs":
        server = head[:-1] if head.endswith(":") else head
        path = tail.strip("/")
        if "@" in server:
            raise ValueError(_NO_LOGIN_IN_ADDRESS)
        if not server or not path:
            raise ValueError("Add the export path after the address, like 192.168.1.50:/volume1/farmhand.")
        return protocol, server, "/" + path

    share = tail.strip("/")
    if "@" in head:
        raise ValueError(_NO_LOGIN_IN_ADDRESS)
    if not head or not share:
        raise ValueError("Add the share name after the address, like //192.168.1.50/farmhand.")
    return protocol, head, share


def validate_fields(
    protocol: str | None,
    server: str | None,
    share: str | None,
    username: str | None = None,
    password: str | None = None,
    domain: str | None = None,
    version: str | None = None,
) -> ShareSpec:
    """Normalise and validate what a person typed. Raises ValueError with a plain-language message."""
    if protocol not in PROTOCOLS:
        raise ValueError("Choose SMB or NFS.")

    server = (server or "").strip()
    if not _HOST.match(server):
        raise ValueError("Enter the NAS's address — its IP (like 192.168.1.50) or its name (like nas.local).")

    raw_share = (share or "").strip()
    if protocol == "smb":
        raw_share = raw_share.strip("/")
        segments = raw_share.split("/")
        if not raw_share or any(seg in ("", ".", "..") for seg in segments) or _SMB_BAD.search(raw_share) or len(raw_share) > 200:
            raise ValueError("Enter the share's name as the NAS lists it (like farmhand), optionally followed by a sub-folder.")
        share_value = raw_share
    else:
        norm = "/" + raw_share.strip("/")
        if not _NFS_PATH.match(norm) or ".." in norm.split("/") or len(norm) > 200:
            raise ValueError("Enter the NFS export path as the NAS lists it (like /volume1/farmhand).")
        share_value = norm

    username = (username or "").strip() or None
    if username is not None and (len(username) > 64 or _CONTROL.search(username)):
        raise ValueError("That username isn't valid.")
    if password is not None and (len(password) > 128 or "\n" in password or "\r" in password or "\x00" in password):
        raise ValueError("That password isn't valid (no line breaks).")
    domain = (domain or "").strip() or None
    if domain is not None and not _DOMAIN.match(domain):
        raise ValueError("That domain/workgroup isn't valid.")

    version = (version or "").strip()
    allowed = SMB_VERSIONS if protocol == "smb" else NFS_VERSIONS
    if protocol == "nfs" and not version:
        version = "4"
    if version not in allowed:
        raise ValueError(f"That {protocol.upper()} version isn't supported here.")

    if protocol == "nfs":
        username = password = domain = None  # NFS has no login of its own
    return ShareSpec(protocol, server, share_value, username, password if username else None, domain, version or None)


# ------------------------------------------------------------------ environment

def _has_cap(bit: int, status_path: str = "/proc/self/status") -> bool:
    try:
        with open(status_path) as f:
            for line in f:
                if line.startswith("CapEff:"):
                    return bool(int(line.split()[1], 16) & (1 << bit))
    except (OSError, ValueError, IndexError):
        pass
    return False


def _has_cap_sys_admin(status_path: str = "/proc/self/status") -> bool:
    return _has_cap(CAP_SYS_ADMIN_BIT, status_path)


COMPOSE_FIX = (
    "Give the api service in docker-compose.yml `cap_add: [SYS_ADMIN, DAC_READ_SEARCH]`, "
    "then run `docker compose up -d` again (see the README)."
)


def mount_capability(status_path: str = "/proc/self/status") -> dict:
    """
    What this process can mount, and why not when it can't.

      ok            can mount at least one kind of share
      smb / nfs     can mount that kind
      message       why `ok` is False
      smb_message / nfs_message   why that particular kind is unavailable (None when it's fine)

    SMB needs two permissions — SYS_ADMIN to mount and DAC_READ_SEARCH, which mount.cifs insists
    on keeping while it drops everything else (without it: "Unable to apply new capability set").
    NFS needs only SYS_ADMIN, so it can work while SMB doesn't.
    """
    smb_tool, nfs_tool = bool(shutil.which("mount.cifs")), bool(shutil.which("mount.nfs"))

    if not _has_cap(CAP_SYS_ADMIN_BIT, status_path):
        msg = "Farmhand's container isn't allowed to mount network shares. " + COMPOSE_FIX
        return {"ok": False, "smb": False, "nfs": False, "message": msg, "smb_message": msg, "nfs_message": msg}

    smb_message = nfs_message = None
    if not smb_tool:
        smb_message = "SMB support (cifs-utils) isn't installed in this image — rebuild it with `docker compose up --build`."
    elif not _has_cap(CAP_DAC_READ_SEARCH_BIT, status_path):
        smb_message = "Mounting SMB shares needs one more permission for the container. " + COMPOSE_FIX
    if not nfs_tool:
        nfs_message = "NFS support (nfs-common) isn't installed in this image — rebuild it with `docker compose up --build`."

    smb, nfs = smb_message is None, nfs_message is None
    message = None if (smb or nfs) else (smb_message if smb_message == nfs_message else f"{smb_message} {nfs_message}")
    return {"ok": smb or nfs, "smb": smb, "nfs": nfs, "message": message, "smb_message": smb_message, "nfs_message": nfs_message}


def is_mounted(path: str | os.PathLike) -> bool:
    try:
        return os.path.ismount(path)
    except OSError:
        return False


# ------------------------------------------------------------------ building the command


def build_mount_command(spec: ShareSpec, mount_point: str | os.PathLike, credentials_file: str | None = None) -> list[str]:
    if spec.protocol == "smb":
        opts = ["uid=0", "gid=0", "file_mode=0664", "dir_mode=0775", "iocharset=utf8"]
        if spec.version:
            opts.append(f"vers={spec.version}")
        opts.append(f"credentials={credentials_file}" if credentials_file else "guest")
        return ["mount", "-t", "cifs", f"//{spec.server}/{spec.share}", str(mount_point), "-o", ",".join(opts)]

    version = spec.version or "4"
    # soft + timeouts: a NAS that goes away yields an error instead of freezing every request that touches it
    opts = [f"vers={version}", "soft", "timeo=100", "retrans=2"]
    if version == "3":
        opts.append("nolock")  # no lock daemon inside the container
    return ["mount", "-t", "nfs", f"{spec.server}:{spec.share}", str(mount_point), "-o", ",".join(opts)]


def _write_credentials(spec: ShareSpec) -> str | None:
    """A 0600 temp file holding the SMB login, or None for guest access. The caller deletes it."""
    if spec.protocol != "smb" or not spec.username:
        return None
    lines = [f"username={spec.username}", f"password={spec.password or ''}"]
    if spec.domain:
        lines.append(f"domain={spec.domain}")
    scratch_dir = "/dev/shm" if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK) else None
    fd, path = tempfile.mkstemp(prefix="farmhand-cred-", dir=scratch_dir)  # mkstemp creates it 0600
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
    except BaseException:
        os.unlink(path)
        raise
    return path


# ------------------------------------------------------------------ running it


def _run(argv: list[str], timeout: int = MOUNT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """Indirection so tests can stand in for the real `mount`."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def friendly_error(stderr: str, spec: ShareSpec) -> MountError:
    """Turn mount's raw output into something a person can act on."""
    text = (stderr or "").strip()
    if spec.password and len(spec.password) >= 4:
        text = text.replace(spec.password, "•••")
    low = text.lower()
    what = "share" if spec.protocol == "smb" else "export"

    if "capability set" in low or "unable to apply new capability" in low:
        return MountError(
            "mount.cifs couldn't adjust its own permissions inside the container — it needs more than the container "
            "was given. " + COMPOSE_FIX,
            "privilege",
        )
    if "operation not permitted" in low or "mount error(1)" in low or "only root" in low or "must be superuser" in low:
        return MountError("Farmhand isn't allowed to mount shares from inside its container. " + COMPOSE_FIX, "privilege")
    if "unknown filesystem type" in low or "mount error(19)" in low:
        return MountError(
            f"This computer's kernel can't mount {spec.protocol.upper()} shares (the {'cifs' if spec.protocol == 'smb' else 'nfs'} "
            "support is missing).",
            "unsupported",
        )
    if "name or service not known" in low or "unable to resolve" in low or "could not resolve" in low or "unknown host" in low:
        return MountError(f"Couldn't find “{spec.server}” on the network. Try its IP address instead of its name.", "unreachable")
    if any(m in low for m in ("no route to host", "network is unreachable", "connection timed out", "mount error(113)", "mount error(110)", "mount error(111)", "connection refused")):
        return MountError(
            f"Couldn't reach {spec.server}. Check the address, that the NAS is switched on, and that it's on the same network.",
            "unreachable",
        )
    if spec.protocol == "nfs" and "access denied" in low:
        return MountError(
            f"{spec.server} refused this computer. On the NAS, allow this machine's IP address to use that export "
            "(and allow root access to it).",
            "permission",
        )
    if "mount error(13)" in low or "permission denied" in low or "access denied" in low or "logon failure" in low:
        return MountError(
            "The NAS refused the connection: wrong username or password, or that user isn't allowed on this share.", "auth"
        )
    if "mount error(2)" in low or "no such file or directory" in low or "bad network name" in low or "mount error(6)" in low:
        return MountError(f"{spec.server} answered, but it has no {what} by that name. Check the {what} name for typos.", "not_found")
    if "mount error(95)" in low or "protocol not supported" in low or "invalid argument" in low or "mount error(22)" in low:
        return MountError(
            f"The NAS didn't accept that {spec.protocol.upper()} version. Try a different version under Advanced.", "version"
        )
    return MountError(f"Couldn't mount the {what}: {text[:300] or 'no details were given'}", "other")


def mount(spec: ShareSpec, mount_point: str | os.PathLike) -> None:
    """Mount the share at mount_point (no-op if it's already mounted). Raises MountError."""
    mount_point = Path(mount_point)
    if is_mounted(mount_point):
        return
    cap = mount_capability()
    if not cap["ok"]:
        raise MountError(cap["message"], "privilege")
    if not cap[spec.protocol]:
        tool_present = shutil.which("mount.cifs" if spec.protocol == "smb" else "mount.nfs")
        raise MountError(cap[f"{spec.protocol}_message"], "privilege" if tool_present else "unsupported")

    mount_point.mkdir(parents=True, exist_ok=True)
    credentials = _write_credentials(spec)
    try:
        argv = build_mount_command(spec, mount_point, credentials)
        try:
            result = _run(argv)
        except subprocess.TimeoutExpired:
            raise MountError(
                f"Timed out waiting for {spec.server}. Check the address and that the NAS is on and reachable.", "unreachable"
            )
        except FileNotFoundError:
            raise MountError("The `mount` command isn't available in this image — rebuild it.", "unsupported")
        if result.returncode != 0:
            raise friendly_error(result.stderr or result.stdout, spec)
    finally:
        if credentials:
            try:
                os.unlink(credentials)
            except FileNotFoundError:
                pass


def unmount(mount_point: str | os.PathLike, lazy: bool = False) -> None:
    """Disconnect a share. Raises MountError("busy") if something is still using it."""
    mount_point = Path(mount_point)
    if not is_mounted(mount_point):
        return
    argv = ["umount", "-l", str(mount_point)] if lazy else ["umount", str(mount_point)]
    try:
        result = _run(argv)
    except subprocess.TimeoutExpired:
        raise MountError("Timed out disconnecting the share. Try again in a moment.", "busy")
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        if "busy" in err.lower():
            raise MountError("The share is busy right now (something is still using it). Try again in a moment.", "busy")
        raise MountError(f"Couldn't disconnect the share: {err[:300] or 'no details were given'}", "other")


# ------------------------------------------------------------------ remembering the last failure per share
# (in memory: it's about the current state of the connection, not something worth saving)

_errors: dict[int, tuple[str, str]] = {}


def set_error(share_id: int, kind: str, message: str) -> None:
    _errors[share_id] = (kind, message)


def clear_error(share_id: int) -> None:
    _errors.pop(share_id, None)


def get_error(share_id: int) -> tuple[str, str] | None:
    return _errors.get(share_id)
