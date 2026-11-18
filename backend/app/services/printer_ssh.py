"""
SSH to a Klipper printer's computer (its Raspberry Pi), for the two things Moonraker won't do over HTTP: hand out its
database file, and write a file it holds read-only (mainsail.cfg, a link into Mainsail's own mainsail-config package).
Used by services/config_backups/ only.

Farmhand has one SSH key of its own, made the first time it's needed and kept in its storage (ssh/id_ed25519). Each
printer lets it in once its public key is added to that Pi's ~/.ssh/authorized_keys (the Backups section shows how). No
password is ever stored or typed. The user and folders come from the printer itself: Moonraker says where its config
folder is (/home/pi/printer_data/config), so the user is "pi" and its data folder /home/pi/printer_data.

The system's own ssh and scp do the work (openssh-client in the image), in batch mode: never a prompt. A printer's host
key is taken on first use and checked after (ssh/known_hosts).
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .. import storage
from ..models import Printer
from .moonraker import client

TIMEOUT = 20  # seconds for a command
COPY_TIMEOUT = 300  # seconds for a copy (a database with years of history is tens of MB)
KEY_NAME = "id_ed25519"
COMMENT = "farmhand"


class SshError(RuntimeError):
    """SSH to the printer didn't work. kind: no_ssh (no ssh program) | no_key (its key isn't on the printer) |
    unreachable | failed"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class Target:
    host: str
    user: str
    data_folder: str  # e.g. /home/pi/printer_data

    @property
    def login(self) -> str:
        return f"{self.user}@{self.host}"


def _folder() -> Path:
    folder = storage.local_root() / "ssh"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def key_path() -> Path:
    """Farmhand's private key, made the first time it's asked for."""
    key = _folder() / KEY_NAME
    if not key.is_file():
        try:
            runner.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", COMMENT, "-f", str(key)], TIMEOUT)
        except FileNotFoundError:
            raise SshError("no_ssh", "This Farmhand has no SSH program (openssh-client): rebuild it with the current image.") from None
        os.chmod(key, 0o600)
    return key


def public_key() -> str:
    """The line to add to a printer's ~/.ssh/authorized_keys."""
    key_path()
    return (_folder() / f"{KEY_NAME}.pub").read_text().strip()


def target(printer: Printer) -> Target:
    """Where and as whom to log in: the IP its Moonraker answers at, and the user and data folder Moonraker reports."""
    base = client.answered_at(printer) or printer.moonraker_url
    host = urlsplit(base or "").hostname
    if not host:
        raise SshError("unreachable", "This printer has no IP address set.")
    config = client.config_root(printer)
    parts = PurePosixPath(config).parts  # ("/", "home", "pi", "printer_data", "config")
    if len(parts) < 4 or parts[1] != "home":
        raise SshError("failed", f"Moonraker's config folder is {config}: Farmhand can't tell which user to log in as.")
    return Target(host=host, user=parts[2], data_folder=str(PurePosixPath(config).parent))


def _options() -> list[str]:
    return [
        "-i", str(key_path()), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={_folder() / 'known_hosts'}",
    ]


def _check(result: subprocess.CompletedProcess, t: Target) -> str:
    if result.returncode == 0:
        return result.stdout
    err = (result.stderr or "").strip()
    if "Permission denied" in err:
        raise SshError("no_key", f"The printer ({t.login}) didn't let Farmhand in: add Farmhand's SSH key to its "
                                 "~/.ssh/authorized_keys (Set up SSH, in the Backups section).")
    if any(w in err for w in ("timed out", "No route to host", "Connection refused", "Could not resolve")):
        raise SshError("unreachable", f"Couldn't reach {t.host} over SSH: {err.splitlines()[-1]}")
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in err:
        raise SshError("failed", f"{t.host} answers SSH with a different host key than before (a reflashed SD card?). "
                                 f"Remove its line from Farmhand's {_folder() / 'known_hosts'} if that's expected.")
    raise SshError("failed", f"SSH to {t.login} failed: {(err.splitlines() or ['no answer'])[-1]}")


def run(t: Target, command: str) -> str:
    """Run a shell command on the printer; its output."""
    try:
        return _check(runner.run(["ssh", *_options(), t.login, command], TIMEOUT), t)
    except FileNotFoundError:
        raise SshError("no_ssh", "This Farmhand has no SSH program (openssh-client): rebuild it with the current image.") from None


# (scp's remote paths aren't quoted: newer scp copies over SFTP, where they aren't read by a shell. Farmhand only copies
# paths with no spaces: the database copies it names itself, and files under the printer's own folders.)


def fetch(t: Target, remote: str, local: Path) -> None:
    """Copy a file from the printer to `local` (written whole or not at all)."""
    part = local.with_name(local.name + ".part")
    try:
        _check(runner.run(["scp", "-q", *_options(), f"{t.login}:{remote}", str(part)], COPY_TIMEOUT), t)
        os.replace(part, local)
    except FileNotFoundError:
        raise SshError("no_ssh", "This Farmhand has no SSH program (openssh-client): rebuild it with the current image.") from None
    finally:
        part.unlink(missing_ok=True)


def send(t: Target, local: Path, remote: str) -> None:
    """Copy `local` to the printer, replacing `remote`: to a temporary name next to it first, then renamed."""
    part = f"{remote}.farmhand-part"
    try:
        _check(runner.run(["scp", "-q", *_options(), str(local), f"{t.login}:{part}"], COPY_TIMEOUT), t)
    except FileNotFoundError:
        raise SshError("no_ssh", "This Farmhand has no SSH program (openssh-client): rebuild it with the current image.") from None
    run(t, f"mv -f {shlex.quote(part)} {shlex.quote(remote)}")


def check(printer: Printer) -> dict:
    """Test SSH: {ok, user, host, error, kind}. Never raises."""
    try:
        t = target(printer)
        run(t, "true")
        return {"ok": True, "user": t.user, "host": t.host, "error": None, "kind": None}
    except SshError as e:
        return {"ok": False, "user": None, "host": None, "error": str(e), "kind": e.kind}
    except client.MoonrakerError as e:
        return {"ok": False, "user": None, "host": None, "error": str(e), "kind": "unreachable"}


class _Runner:
    """Runs ssh / scp / ssh-keygen. Tests swap it (`printer_ssh.runner`) for a stand-in printer."""

    def run(self, args: list[str], timeout: float) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, 255, "", "Connection timed out")


runner = _Runner()
