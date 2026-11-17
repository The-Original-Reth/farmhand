"""
A stand-in for a printer's Pi as Farmhand reaches it over SSH (app/services/printer_ssh.py runs ssh / scp / ssh-keygen
through `printer_ssh.runner`; this answers them instead). Its files are a dict shared with tests/fake_moonraker.py, so
a database copy Moonraker makes there can be fetched, and one sent there can be restored. Until `accepts_key`, it
refuses Farmhand's key, as a Pi does before the key is added to its authorized_keys.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class FakePi:
    def __init__(self, files: dict[str, bytes] | None = None):
        self.files: dict[str, bytes] = files if files is not None else {}  # absolute path on the Pi -> contents
        self.links: dict[str, str] = {}  # a link's path -> the file it really is
        self.accepts_key = False
        self.commands: list[str] = []

    def _done(self, args, out: str = "", code: int = 0, err: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, code, out, err)

    def run(self, args: list[str], timeout: float) -> subprocess.CompletedProcess:
        tool = args[0]
        if tool == "ssh-keygen":
            key = Path(args[args.index("-f") + 1])
            key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n")
            key.with_name(key.name + ".pub").write_text("ssh-ed25519 AAAAfakekey farmhand\n")
            return self._done(args)
        if not self.accepts_key:
            return self._done(args, code=255, err="pi@10.0.6.21: Permission denied (publickey,password).")
        if tool == "ssh":
            command = args[-1]
            self.commands.append(command)
            word, *rest = command.split()
            rest = [r.strip("'") for r in rest]
            if word == "true" or word == "mkdir":
                return self._done(args)
            if word == "rm":
                self.files.pop(rest[-1], None)
                return self._done(args)
            if word == "readlink":
                return self._done(args, out=self.links.get(rest[-1], rest[-1]) + "\n")
            if word == "mv":
                self.files[rest[-1]] = self.files.pop(rest[-2])
                return self._done(args)
            return self._done(args, code=1, err=f"unknown command {command}")
        if tool == "scp":
            src, dst = args[-2], args[-1]
            if ":" in src and src.split(":", 1)[0].count("@"):
                remote = src.split(":", 1)[1]
                if remote not in self.files:
                    return self._done(args, code=1, err=f"scp: {remote}: No such file or directory")
                Path(dst).write_bytes(self.files[remote])
            else:
                self.files[dst.split(":", 1)[1]] = Path(src).read_bytes()
            return self._done(args)
        return self._done(args, code=127, err=f"{tool}: not found")
