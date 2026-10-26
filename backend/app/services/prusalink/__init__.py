"""
Talking to a printer's PrusaLink (Prusa's local API on the Core One, MK4, XL...): its live status, sending it a sliced
file to print, and the print history Farmhand records from it (PrusaLink keeps none).

Everything here goes over the printer's local network with short timeouts, and every failure becomes a PrusaLinkError
that says plainly what went wrong (no address, can't connect, wrong password, busy...).
"""
from __future__ import annotations

from .client import PrusaLinkError, upload_and_print, version
from .tracking import poll, totals

__all__ = ["PrusaLinkError", "poll", "totals", "upload_and_print", "version"]
