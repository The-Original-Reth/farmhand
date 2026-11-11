"""The Stream page: the relay that hands one picture over to the next at a keyframe, and the delay's buffer before YouTube."""
from __future__ import annotations

import threading
import time

import pytest

from .factories import wait_for as _wait_for
from .fake_ffmpeg import _keyframe_packet, _Sink

pytestmark = pytest.mark.usefixtures("stream_fresh")



def test_the_relay_switches_at_a_keyframe_and_the_buffer_holds_the_delay():
    from app.services.live_stream import relay

    key, plain = _keyframe_packet(), bytes([0x47, 0x01, 0x00, 0x10]) + bytes(184)
    start_of_frame = bytes([0x47, 0x41, 0x00, 0x10]) + bytes(184)  # a frame's first packet, not a keyframe
    assert relay.keyframe_at(plain + plain + key + plain) == 2 * 188 and relay.keyframe_at(plain + start_of_frame) is None
    assert relay.last_frame_start(start_of_frame + plain + start_of_frame + plain) == 2 * 188

    class Picture:
        def __init__(self, chunks):
            self.chunks, self.ended = list(chunks), threading.Event()
            self.stdout = self

        def read(self, n=-1):
            if self.chunks:
                return self.chunks.pop(0)
            self.ended.wait()
            return b""

    sink = _Sink()
    r = relay.Relay(sink)
    old = Picture([start_of_frame + plain, start_of_frame + plain])
    r.start(old)
    assert _wait_for(lambda: len(sink.written) == 2 * 188)  # the first whole frame (the second held until the next starts)
    new = Picture([plain + plain, plain + key + plain, start_of_frame])  # warming up: nothing passed on until its first keyframe
    assert r.switch_to(new, timeout=3)
    # from its keyframe on, once that frame is whole (the next one's start held back in turn)
    assert _wait_for(lambda: bytes(sink.written).endswith(key + plain)) and len(sink.written) == 4 * 188
    assert bytes(sink.written[:2 * 188]) == start_of_frame + plain and r.current() is new
    old.ended.set()
    new.ended.set()

    buffer = relay.Buffer(0.5)
    out = _Sink()
    buffer.set_sink(out)
    buffer.write(b"first")
    time.sleep(0.2)
    assert out.written == b"" and buffer.filling() and 0.1 <= buffer.held() <= 0.5  # held for its delay
    assert _wait_for(lambda: out.written == b"first") and not buffer.filling()
    buffer.write(b"then")
    assert _wait_for(lambda: out.written == b"firstthen")  # then passed on as it comes
    buffer.close()


def test_the_buffer_trims_back_to_the_delay_at_a_keyframe(monkeypatch):
    """Held well over the delay (each hand-over adds a little; a sender not taking anything adds a lot): what's older
    is dropped back to a keyframe that leaves about the delay held, so the sender reads on from a whole picture."""
    from app.services.live_stream import relay

    monkeypatch.setattr(relay, "TRIM_OVER", 0.3)
    stuck = threading.Event()

    class Stuck(_Sink):  # a sender that takes the first piece, then nothing more
        def write(self, data):
            super().write(data)
            stuck.wait(5)

    buffer = relay.Buffer(0.1)
    buffer.set_sink(Stuck())
    plain, key = bytes([0x47, 0x01, 0x00, 0x10]) + bytes(184), _keyframe_packet()
    buffer.write(plain)
    assert _wait_for(lambda: not buffer.filling())
    buffer.write(plain + plain)  # old, and no keyframe in it: dropped
    time.sleep(0.45)
    buffer.write(plain + key + plain)  # fresh, with a keyframe: kept from it
    assert buffer.held() < 0.3 and bytes(buffer._chunks[0][1]) == key + plain
    stuck.set()
    buffer.close()


def test_the_relay_knows_the_time_of_the_last_frame_passed_on():
    """A new picture's times carry on from the last frame passed on (not the clock), so after a break the sender,
    playing to the times, has no jump ahead to wait out."""
    from app.services.live_stream import relay

    def frame_at(seconds):
        pts = int(seconds * 90000)
        b = bytes([0x21 | ((pts >> 29) & 0xE), (pts >> 22) & 0xFF, ((pts >> 14) & 0xFE) | 1, (pts >> 7) & 0xFF, ((pts << 1) & 0xFE) | 1])
        pes = bytes([0, 0, 1, 0xE0, 0, 0, 0x80, 0x80, 5]) + b
        return bytes([0x47, 0x41, 0x00, 0x10]) + pes + bytes(184 - len(pes))

    plain = bytes([0x47, 0x01, 0x00, 0x10]) + bytes(184)
    assert relay.last_time(frame_at(3.0) + plain + frame_at(12.5) + plain) == 12.5 and relay.last_time(plain) is None
    sink, ended = _Sink(), threading.Event()

    class Picture:
        def __init__(self):
            self.chunks = [frame_at(1.0) + plain, frame_at(1.5) + plain, frame_at(2.0)]
            self.stdout = self

        def read(self, n=-1):
            if self.chunks:
                return self.chunks.pop(0)
            ended.wait()
            return b""

    r = relay.Relay(sink)
    assert r.last_time() is None
    r.start(Picture())
    assert _wait_for(lambda: r.last_time() == 1.5)  # (the 2.0 s frame is still being held back, not passed on)
    ended.set()
