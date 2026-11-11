from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..timeutil import utc_now


class Plugin(Base):
    """
    A plugin the operator installed: its own container, which reads Farmhand only through the plugin API
    (/plugin-api/v1/, see app/services/plugins and docs/plugins.md). Its manifest (farmhand-plugin.json) is kept as
    it was checked, for the port, page and health check it names.
    """

    __tablename__ = "plugin"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # its slug, e.g. "stream"
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    image: Mapped[str | None] = mapped_column(String(300))  # the Docker image it runs from, when known
    farmhand_api: Mapped[str] = mapped_column(String(8), nullable=False)  # the plugin API version it was written for
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Its token (only ever one at a time: a new one ends the old). Goes with it.
    tokens: Mapped[list["PluginToken"]] = relationship(back_populates="plugin", cascade="all, delete-orphan")


class PluginToken(Base):
    """
    A plugin's key to the plugin API, with the permissions the operator granted it. Only its sha256 is kept: the token
    itself is shown once, when it's made, and handed to the plugin's container as FARMHAND_TOKEN.
    """

    __tablename__ = "plugin_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin_id: Mapped[str] = mapped_column(ForeignKey("plugin.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    permissions: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    plugin: Mapped[Plugin] = relationship(back_populates="tokens")
