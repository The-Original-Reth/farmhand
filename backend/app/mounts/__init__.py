"""
Mounting NAS shares (SMB/CIFS and NFS) from inside the app, so the whole thing can be
set up from the web interface instead of by editing files on the host.

What this needs from the environment (docker-compose.yml provides both):
  * the container must be allowed to mount: the SYS_ADMIN capability — and, for SMB, DAC_READ_SEARCH too
  * the image must have the client tools: mount.cifs (cifs-utils) and mount.nfs (nfs-common)

Mounts live in the container's own mount namespace: they disappear when the container
restarts, so saved shares are re-mounted at startup and kept mounted by a supervisor
(see mount_supervisor.py).

Everything a person types ends up in a subprocess command, so:
  * every field is validated against a strict pattern first,
  * commands are argument lists, never a shell string,
  * an SMB password is passed in a temporary 0600 credentials file — never on the command
    line, where `ps` would show it, and never inside a comma-separated option string, where
    a comma in the password would break parsing.

Nothing here has been run against a real NAS in the environment this was written in; the
commands it builds and the way it reads mount's error output are covered by tests that use
a fake `mount`.
"""
from __future__ import annotations

import logging

from .capability import (
    CAP_DAC_READ_SEARCH_BIT,
    CAP_SYS_ADMIN_BIT,
    COMPOSE_FIX,
    _MOUNT_TOOLS,
    _has_cap,
    _has_cap_sys_admin,
    _not_installed,
    is_mounted,
    mount_capability,
)
from .failures import _errors, clear_error, get_error, set_error
from .running import (
    MOUNT_TIMEOUT_SECONDS,
    MountError,
    _details,
    _require_mount_capability,
    _run,
    _run_mount,
    _write_credentials,
    build_mount_command,
    friendly_error,
    mount,
    unmount,
)
from .shares import (
    NFS_VERSIONS,
    PROTOCOLS,
    SMB_VERSIONS,
    ShareSpec,
    parse_location,
    mount_point_for,
    scratch_mount_point,
    slug,
    validate_fields,
    validate_name,
)

log = logging.getLogger("farmhand.mounts")
