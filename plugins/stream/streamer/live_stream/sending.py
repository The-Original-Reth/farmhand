"""
The live stream's sender: the one connection to YouTube, an ffmpeg passing on what the delay's buffer gives it,
started again whenever it drops; and what every ffmpeg says, kept (the stream key blanked out). Part of runner.Stream.
"""
from __future__ import annotations

import threading
import time

from . import procs
from .buffer import Buffer
from .constants import DESTINATIONS, RETRY_SECONDS

SENDER_STEADY = 30  # seconds a sender connected again has to keep sending before its drop's message is cleared


class SendingMixin:
    """The sender, and what the ffmpegs say (state on runner.Stream)."""

    def _keep_sending(self, gen: int, args: list[str], buffer: Buffer) -> None:
        """The sender, started again whenever it stops (the connection to YouTube dropped), for as long as it's live."""
        while self._current(gen):
            try:
                proc = procs.popen(args, feed=True)
            except OSError as e:
                with self._lock:
                    self._error = f"ffmpeg couldn't be started: {e.strerror or e}"
                    self._wanted.clear()
                return
            with self._lock:
                if not self._current(gen):
                    procs.end(proc)
                    return
                self._sender = proc
            buffer.set_sink(proc.stdin)
            started = time.monotonic()
            threading.Thread(target=self._clear_when_steady, args=(gen, proc), name="stream-sender-ok", daemon=True).start()
            self._listen(proc)
            code = proc.wait()
            if not self._current(gen):
                return
            with self._lock:
                last = next((l for l in reversed(self._said) if l), None)
                self._error = (f"The connection to {self._destination and DESTINATIONS[self._destination]['label'] or 'YouTube'} dropped "
                               f"(ffmpeg exit {code}): {last or 'no reason given'}. Connecting again in {RETRY_SECONDS} s.")
                if time.monotonic() - started > 60:
                    self._said.clear()
            if not self._wait(gen, RETRY_SECONDS):
                return

    def _clear_when_steady(self, gen: int, proc) -> None:
        """A sender connected again and still sending after SENDER_STEADY seconds: the message that it dropped is
        cleared (it said it would connect again, and it has)."""
        if self._wait(gen, SENDER_STEADY) and proc.poll() is None:
            with self._lock:
                if self._error and self._error.startswith("The connection to"):
                    self._error = None

    def _hide_key(self, text: str) -> str:
        return text.replace(self._key, "<stream key>") if self._key else text

    def _listen(self, proc) -> None:
        """What ffmpeg says, kept (the stream key blanked out)."""
        for line in proc.stderr or []:
            line = self._hide_key(line.strip())
            if line:
                self._said.append(line)
