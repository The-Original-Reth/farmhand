"""
Talking to a printer's Moonraker (the API behind Mainsail): its print history and lifetime totals, copied into
Farmhand, and its maintenance reminders, which stay in Moonraker's own database exactly the way Mainsail keeps them
so the two apps share one list.

Everything here goes over the printer's local network with short timeouts, and every failure becomes a
MoonrakerError that says plainly what went wrong (no address, can't connect, needs an API key, ...).
"""
from __future__ import annotations

from .client import MoonrakerError, answered_at, board, board_of, live_print, print_state, server_info, system_info, upload_and_print, webcams
from .history import archive_stats, sync_history
from .maintenance import add_maintenance, delete_maintenance, list_maintenance, perform_maintenance, update_maintenance
from .service import NotesConflict, service_done, set_service_enabled, set_service_notes
from .status import connection_status

__all__ = [
    "MoonrakerError", "NotesConflict",
    "add_maintenance", "answered_at", "archive_stats", "board", "board_of", "connection_status", "delete_maintenance", "list_maintenance", "live_print",
    "perform_maintenance", "print_state", "upload_and_print", "server_info", "service_done", "set_service_enabled", "set_service_notes",
    "sync_history", "system_info", "update_maintenance", "webcams",
]
