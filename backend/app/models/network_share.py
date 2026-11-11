from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..timeutil import utc_now


class NetworkShare(Base):
    """
    A NAS share Farmhand mounts for itself (added on the Storage page).

    NOTE: the password is stored as-is — Farmhand has to be able to present it again to
    re-mount the share after every restart, and there's nowhere safer than this database to
    keep a key for encrypting it. It is never sent back out through the API.
    """

    __tablename__ = "network_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), nullable=False)  # "smb" | "nfs"
    server: Mapped[str] = mapped_column(String(255), nullable=False)
    share: Mapped[str] = mapped_column(String(255), nullable=False)  # SMB: share[/sub/path]; NFS: export path
    username: Mapped[str | None] = mapped_column(String(64))
    password: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
