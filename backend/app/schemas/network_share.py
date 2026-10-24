from __future__ import annotations

from pydantic import BaseModel


class NetworkShareCreate(BaseModel):
    """
    Give the NAS folder as ONE `location` (//192.168.1.50/farmhand/Projects, 192.168.1.50:/volume1/farmhand,
    smb://…, nfs://…) — the protocol, server and share are worked out from it. The separate
    protocol/server/share fields are still accepted for callers that already have them split.
    """

    name: str
    location: str | None = None
    protocol: str | None = None  # "smb" | "nfs"
    server: str | None = None
    share: str | None = None
    username: str | None = None
    password: str | None = None
    domain: str | None = None
    version: str | None = None


class NetworkShareUpdate(BaseModel):
    """
    Only fields present are changed. An omitted/empty password keeps the saved one;
    an empty username switches to guest access. `location` replaces server+share in one go
    (the protocol of an existing share can't change).
    """

    location: str | None = None
    server: str | None = None
    share: str | None = None
    username: str | None = None
    password: str | None = None
    domain: str | None = None
    version: str | None = None


class MountCapability(BaseModel):
    ok: bool  # can mount at least one kind of share
    smb: bool
    nfs: bool
    message: str | None  # why `ok` is False
    smb_message: str | None = None  # why SMB specifically isn't available (NFS can work without it)
    nfs_message: str | None = None


class NetworkShareOut(BaseModel):
    id: int
    name: str
    protocol: str
    server: str
    share: str
    username: str | None
    domain: str | None
    version: str | None
    has_password: bool  # the password itself is never returned
    address: str  # smb://server/share or nfs://server/export
    mount_point: str
    mounted: bool
    error: str | None
    error_kind: str | None
    files_here: int  # versions whose files are stored on this share


class SharesOut(BaseModel):
    shares: list[NetworkShareOut]
    capability: MountCapability


class FolderCreate(BaseModel):
    parent: str
    name: str
