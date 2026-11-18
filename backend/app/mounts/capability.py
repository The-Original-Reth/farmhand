"""What this container may mount: its permissions (SYS_ADMIN, and DAC_READ_SEARCH for SMB) and whether the
mount tools are installed, plus whether a folder is mounted right now."""
from __future__ import annotations

import os
import shutil

CAP_SYS_ADMIN_BIT = 21
CAP_DAC_READ_SEARCH_BIT = 2  # mount.cifs refuses to run without it, on top of SYS_ADMIN
_MOUNT_TOOLS = {"smb": "mount.cifs", "nfs": "mount.nfs"}


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
    smb_tool, nfs_tool = (bool(shutil.which(_MOUNT_TOOLS[p])) for p in ("smb", "nfs"))

    if not _has_cap(CAP_SYS_ADMIN_BIT, status_path):
        msg = "Farmhand's container isn't allowed to mount network shares. " + COMPOSE_FIX
        return {"ok": False, "smb": False, "nfs": False, "message": msg, "smb_message": msg, "nfs_message": msg}

    smb_message = nfs_message = None
    if not smb_tool:
        smb_message = _not_installed("SMB", "cifs-utils")
    elif not _has_cap(CAP_DAC_READ_SEARCH_BIT, status_path):
        smb_message = "Mounting SMB shares needs one more permission for the container. " + COMPOSE_FIX
    if not nfs_tool:
        nfs_message = _not_installed("NFS", "nfs-common")

    smb, nfs = smb_message is None, nfs_message is None
    message = None if (smb or nfs) else (smb_message if smb_message == nfs_message else f"{smb_message} {nfs_message}")
    return {"ok": smb or nfs, "smb": smb, "nfs": nfs, "message": message, "smb_message": smb_message, "nfs_message": nfs_message}


def _not_installed(protocol: str, package: str) -> str:
    return f"{protocol} support ({package}) isn't installed in this image — rebuild it with `docker compose up --build`."


def is_mounted(path: str | os.PathLike) -> bool:
    try:
        return os.path.ismount(path)
    except OSError:
        return False
