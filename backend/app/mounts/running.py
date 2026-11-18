"""Building the mount command, running it (and umount), and turning mount's own output into a message a person
can act on. Tests stand in for the real `mount` by replacing `_run` here."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .capability import COMPOSE_FIX, _MOUNT_TOOLS, _has_cap_sys_admin, is_mounted, mount_capability
from .shares import ShareSpec

MOUNT_TIMEOUT_SECONDS = 30


class MountError(ValueError):
    """Mounting/unmounting failed. The message is written to be shown to the person using the app."""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind  # auth | permission | not_found | unreachable | privilege | unsupported | version | busy | other


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


def friendly_error(stderr: str, spec: ShareSpec, allowed: bool | None = None) -> MountError:
    """
    Turn mount's raw output into something a person can act on. `allowed`: whether this container may mount at all
    (None: look). When it may, "Operation not permitted" (mount error 1) is the NAS saying no, not the container: a
    wrong login, guest access turned off, or an SMB version it won't use.
    """
    if allowed is None:
        allowed = _has_cap_sys_admin()
    text = (stderr or "").strip()
    if spec.password and len(spec.password) >= 4:
        text = text.replace(spec.password, "•••")
    low = text.lower()

    def says(*phrases: str) -> bool:
        return any(phrase in low for phrase in phrases)

    what = "share" if spec.protocol == "smb" else "export"
    proto = spec.protocol.upper()

    if says("capability set", "unable to apply new capability"):
        return MountError(
            "mount.cifs couldn't adjust its own permissions inside the container — it needs more than the container "
            "was given. " + COMPOSE_FIX,
            "privilege",
        )
    if says("only root", "must be superuser") or (says("operation not permitted", "mount error(1)") and not allowed):
        return MountError("Farmhand isn't allowed to mount shares from inside its container. " + COMPOSE_FIX, "privilege")
    if says("operation not permitted", "mount error(1)"):
        if spec.protocol == "nfs":
            return MountError(
                f"{spec.server} refused this computer. On the NAS, allow this machine's IP address to use that export "
                "(and allow root access to it).",
                "permission",
            )
        login = (
            f"that the username ({spec.username}) and password are right and that user may use this share"
            if spec.username
            else "that the NAS lets guests use this share, or give a username and password"
        )
        return MountError(
            f"The NAS turned the connection down (mount error 1). Check {login}; if they are, try another SMB version "
            "under Advanced (Farmhand's container is allowed to mount shares, so this is the NAS saying no).",
            "auth",
        )
    if says("unknown filesystem type", "mount error(19)"):
        return MountError(
            f"This computer's kernel can't mount {proto} shares (the {'cifs' if spec.protocol == 'smb' else 'nfs'} "
            "support is missing).",
            "unsupported",
        )
    if says("name or service not known", "unable to resolve", "could not resolve", "unknown host"):
        return MountError(f"Couldn't find “{spec.server}” on the network. Try its IP address instead of its name.", "unreachable")
    if says("no route to host", "network is unreachable", "connection timed out", "mount error(113)", "mount error(110)",
            "mount error(111)", "connection refused"):
        return MountError(
            f"Couldn't reach {spec.server}. Check the address, that the NAS is switched on, and that it's on the same network.",
            "unreachable",
        )
    if spec.protocol == "nfs" and says("access denied"):
        return MountError(
            f"{spec.server} refused this computer. On the NAS, allow this machine's IP address to use that export "
            "(and allow root access to it).",
            "permission",
        )
    if says("mount error(13)", "permission denied", "access denied", "logon failure"):
        return MountError(
            "The NAS refused the connection: wrong username or password, or that user isn't allowed on this share.", "auth"
        )
    if says("mount error(2)", "no such file or directory", "bad network name", "mount error(6)"):
        return MountError(f"{spec.server} answered, but it has no {what} by that name. Check the {what} name for typos.", "not_found")
    if says("mount error(95)", "protocol not supported", "invalid argument", "mount error(22)"):
        return MountError(
            f"The NAS didn't accept that {proto} version. Try a different version under Advanced.", "version"
        )
    return MountError(f"Couldn't mount the {what}: {_details(text)}", "other")


def _details(output: str) -> str:
    """The start of a command's own output, for the end of a message."""
    return output[:300] or "no details were given"


def mount(spec: ShareSpec, mount_point: str | os.PathLike) -> None:
    """Mount the share at mount_point (no-op if it's already mounted). Raises MountError."""
    mount_point = Path(mount_point)
    if is_mounted(mount_point):
        return
    _require_mount_capability(spec.protocol)

    mount_point.mkdir(parents=True, exist_ok=True)
    credentials = _write_credentials(spec)
    try:
        _run_mount(spec, build_mount_command(spec, mount_point, credentials))
    finally:
        if credentials:
            Path(credentials).unlink(missing_ok=True)


def _require_mount_capability(protocol: str) -> None:
    """Raise MountError when this container can't mount this kind of share (privilege, or a missing client tool)."""
    cap = mount_capability()
    if not cap["ok"]:
        raise MountError(cap["message"], "privilege")
    if not cap[protocol]:
        tool_present = shutil.which(_MOUNT_TOOLS[protocol])
        raise MountError(cap[f"{protocol}_message"], "privilege" if tool_present else "unsupported")


def _run_mount(spec: ShareSpec, argv: list[str]) -> None:
    try:
        result = _run(argv)
    except subprocess.TimeoutExpired:
        raise MountError(
            f"Timed out waiting for {spec.server}. Check the address and that the NAS is on and reachable.", "unreachable"
        )
    except FileNotFoundError:
        raise MountError("The `mount` command isn't available in this image — rebuild it.", "unsupported")
    if result.returncode != 0:
        # mount() has already checked this container may mount this kind of share
        raise friendly_error(result.stderr or result.stdout, spec, allowed=True)


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
        raise MountError(f"Couldn't disconnect the share: {_details(err)}", "other")
