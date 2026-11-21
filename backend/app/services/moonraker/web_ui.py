"""
Which web page a Klipper printer serves on port 80: Mainsail or Fluidd. Both talk to the same Moonraker and read the
same camera settings (Moonraker's webcams), so Farmhand treats the printer the same either way: only the name on its
buttons, links and wording follows what the printer runs.

Found by asking for the page itself (its <title> says "Mainsail" or "Fluidd"), at each Moonraker sync and Sync now.
A page that can't be fetched, or says neither, leaves what was found before (Mainsail until something is found).
"""
from __future__ import annotations

import datetime as dt
import re

import httpx
from sqlalchemy.orm import Session

from ...models import Printer, PrinterWebUi
from ...timeutil import as_utc, utc_now
from . import client

NAMES = ("Fluidd", "Mainsail")
TIMEOUT = httpx.Timeout(3.0, connect=1.5)
RECHECK = dt.timedelta(minutes=15)  # how long what was found counts before the Printers page has it looked at again
READ_AT_MOST = 64 * 1024  # the title is near the top; an odd page isn't read whole

_TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def name_in(page: bytes) -> str | None:
    """"Mainsail" or "Fluidd" from a page's HTML: its title first, else the first of them the page names. None for neither."""
    m = _TITLE.search(page)
    for text in ((m.group(1),) if m else ()) + (page,):
        lowered = text.lower()
        found = [(lowered.find(n.lower().encode()), n) for n in NAMES if n.lower().encode() in lowered]
        if found:
            return min(found)[1]
    return None


def detect(printer: Printer) -> str | None:
    """Ask the printer's port 80 page which it is. None when it can't be reached or says neither."""
    return detect_at(printer.mainsail_url)


def detect_at(url: str | None) -> str | None:
    """The same, for a page's address ("http://10.0.6.21/"), e.g. one a network scan found."""
    if not url:
        return None
    try:
        with httpx.Client(timeout=TIMEOUT, transport=client.transport, follow_redirects=True) as http:
            with http.stream("GET", url) as r:
                if r.status_code >= 400:
                    return None
                page = b""
                for chunk in r.iter_bytes():
                    page += chunk
                    if len(page) >= READ_AT_MOST:
                        break
    except httpx.HTTPError:
        return None
    return name_in(page)


def refresh(db: Session, printer: Printer) -> str | None:
    """Look again and keep what's found (committed). Returns the printer's web UI now."""
    if printer.connection_type != "moonraker":
        return None
    found = detect(printer)
    if found:
        row = printer.web_ui_row
        if row is None:
            printer.web_ui_row = PrinterWebUi(name=found, checked_at=utc_now())
        else:
            row.name, row.checked_at = found, utc_now()
        db.commit()
    return printer.web_ui


def refresh_if_due(db: Session, printer: Printer) -> str | None:
    """refresh(), unless it was looked at in the last RECHECK (for the Printers page, which asks often)."""
    row = printer.web_ui_row
    if row is not None and utc_now() - as_utc(row.checked_at) < RECHECK:
        return printer.web_ui
    if row is not None:
        row.checked_at = utc_now()  # one that can't be reached now isn't asked again at every look either
        db.commit()
    return refresh(db, printer)
