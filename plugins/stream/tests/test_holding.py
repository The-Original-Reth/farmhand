"""
The holding screen: what YouTube is shown after the plugin's own restart while the delay fills again.
"""
from __future__ import annotations

import pytest

from streamer import store

from .conftest import wait_until

from .conftest import grid

pytestmark = pytest.mark.usefixtures("stream_fresh")


# ------------------------------------------------------------------ the holding screen, after the plugin's own restart


def test_the_holding_screen_is_saved_with_the_streams_settings(api, plugin):
    page = api.get("/api/stream").json()
    assert page["settings"]["holding"] == {"text": "Back in a minute", "image": None, "background": None, "color": None, "font": None}
    r = api.put("/api/stream", json={"holding": {"text": "  Back soon\nKeep watching  ", "background": "#112233", "font": "roboto"}})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["holding"] == {"text": "Back soon\nKeep watching", "image": None, "background": "#112233", "color": None, "font": "roboto"}
    # only what's sent changes; null: the stream's own again
    r = api.put("/api/stream", json={"holding": {"background": None, "color": "#ffffff"}})
    assert r.json()["settings"]["holding"] == {"text": "Back soon\nKeep watching", "image": None, "background": None, "color": "#FFFFFF", "font": "roboto"}
    assert api.put("/api/stream", json={"holding": {"color": "red"}}).status_code == 422
    assert api.put("/api/stream", json={"holding": {"font": "comic"}}).status_code == 422
    assert api.put("/api/stream", json={"holding": {"text": "x" * 301}}).status_code == 422


def test_the_holding_screen_is_drawn_at_the_streams_size_with_its_words_centred(tmp_path):
    from PIL import Image

    from streamer.live_stream import fonts, holding

    logo = tmp_path / "logo.png"
    Image.new("RGB", (100, 50), (0, 0, 255)).save(logo)
    out = tmp_path / "holding.png"
    holding.draw(str(out), 1280, 720, "Back\nin a minute", "#FFFFFF", "#FF0000", fonts.font_file(None), str(logo))
    with Image.open(out) as im:
        im = im.convert("RGB")
        assert im.size == (1280, 720)
        blue = [(x, y) for y in range(0, 720, 4) for x in range(0, 1280, 4) if im.getpixel((x, y)) == (0, 0, 255)]
        assert blue and max(y for _, y in blue) < 0.66 * 720  # the picture, fitted above the words
        assert abs((min(x for x, _ in blue) + max(x for x, _ in blue)) / 2 - 640) < 10
        red = [(x, y) for y in range(0, 720, 2) for x in range(0, 1280, 2) if im.getpixel((x, y))[0] > 200 and im.getpixel((x, y))[1] < 80]
        top = min(y for _, y in red)
        first = [x for x, y in red if y < top + 0.06 * 720]  # "Back", the short first line: centred
        assert abs((min(first) + max(first)) / 2 - 640) < 0.02 * 1280
    holding.draw(str(out), 1280, 720, "Back soon", "#000000", "#FFFFFF", fonts.font_file(None), str(tmp_path / "gone.png"))
    assert out.exists()  # (a picture that's gone: the words alone)


def test_the_buffer_gives_the_holding_screen_until_the_delay_is_held_then_whats_held():
    """After a restart the sender is given the holding screen at once, in whole frames, while the delay fills; once it's
    held, what's held goes out from its start and the holding screen is ended."""
    from streamer.live_stream import buffer as relay

    from .fake_ffmpeg import HOLDING_FRAME, _Holding, _Sink

    buffer, sink, hold = relay.Buffer(0.4), _Sink(), _Holding()
    buffer.set_sink(sink)
    buffer.fill_from(hold)
    buffer.write(b"\x47" + b"P" * 187)  # the live picture starts coming in (no times in it: counted by the clock)
    assert wait_until(lambda: HOLDING_FRAME in bytes(sink.written), timeout=1)
    assert buffer.filling() and buffer.filled_from() is hold
    assert wait_until(lambda: b"P" * 187 in bytes(sink.written), timeout=3)
    assert hold.poll() is not None and buffer.filled_from() is None and not buffer.filling()
    sent = bytes(sink.written)
    before = sent[: sent.index(b"\x47" + b"P" * 187)]
    assert before and len(before) % 188 == 0 and before.count(b"HOLD") == len(before) // 188  # whole holding frames only
    buffer.close()


def test_going_live_again_after_a_restart_shows_the_holding_screen_while_the_delay_fills(api, ffmpeg, farmhand, plugin):
    from streamer.live_stream import stream

    grid(api, [{"camera": "1:Bed"}, None])
    api.put("/api/stream", json={"delay": 1, "holding": {"text": "Back soon"}})
    stream.go_live(store.store(), store.session_factory, resumed=True)
    assert wait_until(lambda: len(ffmpeg.holdings) == 1)
    assert ffmpeg.holdings[0][ffmpeg.holdings[0].index("-i") + 1].endswith("holding.png")
    assert api.get("/api/stream").json()["status"]["holding"] is True
    stream._buffer.write(b"G" + bytes(187))  # (the stand-in picture passes on nothing more of its own)
    assert wait_until(lambda: ffmpeg.holding_procs[0].poll() is not None, timeout=5)  # the delay held: it's ended
    assert api.get("/api/stream").json()["status"]["holding"] is False
    stream.stop()

    stream.go_live(store.store(), store.session_factory)  # Go live itself: no holding screen
    assert wait_until(lambda: len(ffmpeg.senders) == 2)
    assert len(ffmpeg.holdings) == 1
