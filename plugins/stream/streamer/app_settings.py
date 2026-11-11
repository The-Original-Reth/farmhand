"""Farmhand's app_settings get/put, over the plugin's own Store (store.py), for the code copied from Farmhand."""
from __future__ import annotations

from .store import Store


def get(db: Store, key: str) -> str | None:
    return db.get(key)


def put(db: Store, key: str, value: str | None) -> None:
    db.put(key, value)
