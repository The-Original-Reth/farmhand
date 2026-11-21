from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class PrinterCamera(Base):
    """
    A camera Farmhand plays itself, for a printer whose own software doesn't share one: a Prusa's Buddy3D camera,
    which only streams over RTSP. Farmhand hands the stream to go2rtc (see app/services/go2rtc.py), which turns it
    into something a browser plays.

    Its own table, not a column on printers: the database is built with create_all, which creates missing tables but
    never adds columns to ones that exist.
    """

    __tablename__ = "printer_camera"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)  # the camera's IP or host, or a whole rtsp:// URL

    printer: Mapped["Printer"] = relationship(back_populates="camera_row")  # noqa: F821


class PrinterCameraNetwork(Base):
    """
    Which of a printer's two IPs its cameras are reached at, when it has both and the person chose: "wired" or
    "wireless" (the Camera switch on its Edit page). No row: its wired IP when it has one, else its wireless one (see
    Printer.camera_network). Its own table for the same reason as PrinterCamera's.
    """

    __tablename__ = "printer_camera_network"

    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    network: Mapped[str] = mapped_column(String(16), nullable=False)  # "wired" | "wireless"

    printer: Mapped["Printer"] = relationship(back_populates="camera_network_row")  # noqa: F821
