"""The settings themselves (appearance and preferences), as the server holds them."""
from __future__ import annotations

import datetime as dt
import json
import logging

from sqlalchemy.orm import Session

from ... import config_store
from .. import app_settings


log = logging.getLogger("farmhand.settings")

KEY_CONFIG = "config_json"  # the settings themselves (appearance + preferences), as the server holds them


def get_config(db: Session) -> dict:
    try:
        raw = json.loads(app_settings.get(db, KEY_CONFIG) or "{}")
    except ValueError:
        raw = {}
    return config_store.normalize_config(raw)


def save_config(db: Session, patch: dict) -> dict:
    """
    Replace the parts given: the appearance as a whole, and each preference given (the Models sort, the Monitor order)
    on its own. Everything else is left alone.
    """
    current = get_config(db)
    prefs = dict(patch.get("preferences") or {})
    if "energy_price_per_kwh" in prefs and "energy_price_history" not in prefs:
        prefs["energy_price_history"] = _new_price_history(current["preferences"], prefs)
    prefs.pop("energy_price_from", None)
    merged = {
        "appearance": patch["appearance"] if patch.get("appearance") is not None else current["appearance"],
        "preferences": {**current["preferences"], **prefs},
    }
    config = config_store.normalize_config(merged)
    app_settings.put(db, KEY_CONFIG, json.dumps(config))
    db.commit()
    return config


def _new_price_history(current: dict, prefs: dict) -> list[dict]:
    """
    The average cost per kWh's history after it's set to a new price: the new price counts from `energy_price_from`
    (the month it is in the viewer's time zone, "2026-11"; this month in UTC if not given) on. Months before it keep
    the price they had: an earlier entry is never changed. Setting it again in the same month replaces that month's.
    """
    price = config_store.normalize_preferences({"energy_price_per_kwh": prefs["energy_price_per_kwh"]})["energy_price_per_kwh"]
    month = prefs.get("energy_price_from")
    if not (isinstance(month, str) and config_store.is_month(month)):
        month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    history = [e for e in current.get("energy_price_history") or [] if e["from"] < month]
    old = current.get("energy_price_per_kwh")
    if not current.get("energy_price_history") and old is not None and price != old:
        # a price set before there was a history: it keeps counting for the months before this one
        history = [{"from": "0001-01", "price": old}]
    if history and history[-1]["price"] == price:
        return history  # no change from what already counts
    return [*history, {"from": month, "price": price}]
