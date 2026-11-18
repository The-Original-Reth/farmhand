"""What a NAS share is, and checking what a person typed for one: the name, the pasted address, the login and
the version. Everything here ends up in a mount command, so every field is held to a strict pattern."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .. import storage

PROTOCOLS = ("smb", "nfs")
SMB_VERSIONS = ("", "3.1.1", "3.0", "2.1")  # "" = let the kernel negotiate
NFS_VERSIONS = ("4", "3")


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


def _nas_root() -> Path:
    return storage.browse_root() / "nas"


def mount_point_for(name: str) -> Path:
    """Where a share is mounted inside the container — under the folder picker's reach."""
    return _nas_root() / slug(name)


def scratch_mount_point(share_id: int) -> Path:
    """A temporary mount point (hidden from the picker) for trying new settings without touching a live mount."""
    return _nas_root() / f".test-{share_id}"


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
    protocol, rest = _split_protocol(raw)
    head, _, tail = rest.lstrip("/").partition("/")
    if protocol == "nfs":
        return _nfs_location(head, tail)
    return _smb_location(head, tail)


def _split_protocol(raw: str) -> tuple[str, str]:
    """("smb" or "nfs", the address without its scheme or leading //)."""
    m = _SCHEME.match(raw)
    if m:
        scheme = m.group(1).lower()
        if scheme in ("smb", "cifs"):
            return "smb", m.group(2)
        if scheme == "nfs":
            return "nfs", m.group(2)
        raise ValueError(
            "That doesn't look like a NAS address. Use //server/share (SMB) or server:/export (NFS), "
            "or an smb:// or nfs:// address."
        )
    if raw.startswith("//"):
        return "smb", raw[2:]
    if re.match(r"^[^/]*:", raw):  # "host:/path" — a colon before any slash
        return "nfs", raw
    return "smb", raw


def _nfs_location(head: str, tail: str) -> tuple[str, str, str]:
    server = head[:-1] if head.endswith(":") else head
    path = tail.strip("/")
    if "@" in server:
        raise ValueError(_NO_LOGIN_IN_ADDRESS)
    if not server or not path:
        raise ValueError("Add the export path after the address, like 192.168.1.50:/volume1/farmhand.")
    return "nfs", server, "/" + path


def _smb_location(head: str, tail: str) -> tuple[str, str, str]:
    share = tail.strip("/")
    if "@" in head:
        raise ValueError(_NO_LOGIN_IN_ADDRESS)
    if not head or not share:
        raise ValueError("Add the share name after the address, like //192.168.1.50/farmhand.")
    return "smb", head, share


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

    share_value = _valid_smb_share(share) if protocol == "smb" else _valid_nfs_export(share)
    username, password, domain = _valid_login(username, password, domain)
    version = _valid_version(protocol, version)

    if protocol == "nfs":
        username = password = domain = None  # NFS has no login of its own
    return ShareSpec(protocol, server, share_value, username, password if username else None, domain, version or None)


def _valid_smb_share(share: str | None) -> str:
    raw_share = (share or "").strip().strip("/")
    segments = raw_share.split("/")
    if not raw_share or any(seg in ("", ".", "..") for seg in segments) or _SMB_BAD.search(raw_share) or len(raw_share) > 200:
        raise ValueError("Enter the share's name as the NAS lists it (like farmhand), optionally followed by a sub-folder.")
    return raw_share


def _valid_nfs_export(share: str | None) -> str:
    norm = "/" + (share or "").strip().strip("/")
    if not _NFS_PATH.match(norm) or ".." in norm.split("/") or len(norm) > 200:
        raise ValueError("Enter the NFS export path as the NAS lists it (like /volume1/farmhand).")
    return norm


def _valid_login(username: str | None, password: str | None, domain: str | None) -> tuple[str | None, str | None, str | None]:
    """The SMB login fields, tidied (blank -> None) and checked."""
    username = (username or "").strip() or None
    if username is not None and (len(username) > 64 or _CONTROL.search(username)):
        raise ValueError("That username isn't valid.")
    if password is not None and (len(password) > 128 or "\n" in password or "\r" in password or "\x00" in password):
        raise ValueError("That password isn't valid (no line breaks).")
    domain = (domain or "").strip() or None
    if domain is not None and not _DOMAIN.match(domain):
        raise ValueError("That domain/workgroup isn't valid.")
    return username, password, domain


def _valid_version(protocol: str, version: str | None) -> str:
    """The protocol version, or "" for SMB's "let the kernel negotiate". NFS defaults to 4."""
    version = (version or "").strip()
    allowed = SMB_VERSIONS if protocol == "smb" else NFS_VERSIONS
    if protocol == "nfs" and not version:
        version = "4"
    if version not in allowed:
        raise ValueError(f"That {protocol.upper()} version isn't supported here.")
    return version
