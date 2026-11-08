"""A stand-in for the NAS and the kernel's mount table, for the network share tests."""
from __future__ import annotations

import os
from pathlib import Path


class FakeNas:
    """The NAS and the kernel's mount table, in one: mounting works unless told to fail."""

    def __init__(self):
        self.mounted: set[str] = set()
        self.mount_calls: list = []
        self.fail_with: Exception | None = None
        self.fail_scratch: Exception | None = None  # fail only the scratch mount used to try new settings

    def mount(self, spec, mount_point):
        mp = os.path.realpath(str(mount_point))
        self.mount_calls.append((spec, mp))
        if mp in self.mounted:
            return
        err = self.fail_scratch if (".test-" in mp and self.fail_scratch) else self.fail_with
        if err:
            raise err
        Path(mp).mkdir(parents=True, exist_ok=True)
        self.mounted.add(mp)

    def unmount(self, mount_point, lazy=False):
        self.mounted.discard(os.path.realpath(str(mount_point)))

    def is_mounted(self, path):
        return os.path.realpath(str(path)) in self.mounted
