"""The Stream page: the music, played by Farmhand and fed to ffmpeg as it plays."""
from __future__ import annotations

import os
import time

import pytest

from .factories import api_db as _db, wait_for as _wait_for, webcam as _cam
from .fake_ffmpeg import _Sink

pytestmark = pytest.mark.usefixtures("stream_fresh")

KEY = "abcd-efgh-ijkl-mnop-qrst"


def test_the_music(klipper, moonraker, ffmpeg, monkeypatch):
    from app.services import stream_media
    from app.services.live_stream import music

    api, pid = klipper
    # MP3s only, uploaded into music/ (a second of the same name numbered), or copied in by hand
    r = api.post("/stream/music", files=[("files", ("Lofi Chill.mp3", b"ID3one", "audio/mpeg")), ("files", ("lofi chill.MP3", b"ID3two", "audio/mpeg"))])
    assert r.status_code == 201 and r.json()["media"]["music"] == ["lofi chill (2).MP3", "Lofi Chill.mp3"]
    assert "MP3" in api.post("/stream/music", files=[("files", ("song.flac", b"fLaC", "audio/flac"))]).json()["detail"]
    got = api.get("/stream/music/Lofi Chill.mp3")
    assert got.content == b"ID3one" and got.headers["content-type"] == "audio/mpeg"
    assert api.get("/stream/music/nope.mp3").status_code == 404
    root = stream_media.folder(_db(api))
    (root / "music" / "It's 2 am.mp3").write_bytes(b"ID3three")
    assert api.post("/stream/scan").json()["media"]["music"] == ["It's 2 am.mp3", "lofi chill (2).MP3", "Lofi Chill.mp3"]

    # on unless turned off; its volume and shuffling; a volume out of range is refused; no controlling it while not live
    assert "0 to 100" in api.put("/stream", json={"music_volume": 101}).json()["detail"]
    s = api.put("/stream", json={"music_volume": 40, "music_shuffle": False}).json()["settings"]
    assert (s["music"], s["music_volume"], s["music_shuffle"]) == (True, 40, False)
    assert "isn't live" in api.post("/stream/music/next").json()["detail"]
    assert api.post("/stream/music/louder").status_code == 404

    # live: the music starts with the stream, fed to ffmpeg's stdin as it plays (each track decoded to a tone of its own)
    from sqlalchemy.orm import sessionmaker

    from app import database

    monkeypatch.setattr(music, "decoder", _fake_decoder)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=_db(api).get_bind(), future=True))  # (the music reads the tracks itself)
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False})
    api.post("/stream/start")
    assert _wait_for(lambda: ffmpeg.commands)
    cmd = ffmpeg.commands[0]
    at = cmd.index("pipe:0")
    assert cmd[at - 7:at + 1] == ["-f", "s16le", "-ar", "44100", "-ac", "2", "-i", "pipe:0"] and "anullsrc" not in " ".join(cmd)
    assert "-t" not in cmd and "-af" not in cmd  # (no day's end: the music goes on as long as the stream)
    assert _wait_for(lambda: (api.get("/stream").json()["status"]["music"] or {}).get("track") == "It's 2 am.mp3")
    assert api.get("/stream").json()["status"]["music"]["playing"] is True

    # next and back, straight away and with no new ffmpeg
    assert api.post("/stream/music/next").json()["status"]["music"]["track"] in (None, "It's 2 am.mp3", "lofi chill (2).MP3")
    assert _wait_for(lambda: api.get("/stream").json()["status"]["music"]["track"] == "lofi chill (2).MP3")
    api.post("/stream/music/back")  # in its first seconds: the one before
    assert _wait_for(lambda: api.get("/stream").json()["status"]["music"]["track"] == "It's 2 am.mp3")
    assert not api.post("/stream/music/pause").json()["status"]["music"]["playing"]
    assert api.post("/stream/music/play").json()["status"]["music"]["playing"]
    # its settings follow while live, again with no new ffmpeg; turned off, it can't be controlled
    api.put("/stream", json={"music_volume": 60})
    assert api.put("/stream", json={"music": False}).json()["status"]["music"]["on"] is False
    assert "music is off" in api.post("/stream/music/next").json()["detail"]
    assert len(ffmpeg.commands) == 1 and len(ffmpeg.procs[0].stdin.written) > 0

    for name in ("It's 2 am.mp3", "lofi chill (2).MP3", "Lofi Chill.mp3"):
        assert api.delete(f"/stream/music/{name}?confirm=true").status_code == 200
    assert api.delete("/stream/music/Lofi Chill.mp3?confirm=true").status_code == 404


class _Decoded:
    """A track as the stand-in decoder gives it: a quarter of a second of one sample value, its own."""

    def __init__(self, value):
        import io
        from array import array

        self.stdout = io.BytesIO(array("h", [value] * (44100 // 4 * 2)).tobytes())

    def kill(self):
        pass

    def wait(self):
        return 0


_TONES = {}


def _fake_decoder(ffmpeg, path):
    return _Decoded(_TONES.setdefault(os.path.basename(path), 1000 * (len(_TONES) + 1)))


def _player(tracks, **kw):
    from app.services.live_stream import music

    sink = _Sink()
    p = music.Player("ffmpeg", lambda: list(tracks), **{"on": True, "shuffle": False, "volume": 100, **kw})
    p.attach(sink)
    return p, sink


def test_the_music_player(monkeypatch):
    """The music while live: written at the pace it plays, track after track and round again, skipped, gone back,
    paused, quietened and turned off as it goes."""
    from array import array

    from app.services.live_stream import music

    monkeypatch.setattr(music, "decoder", _fake_decoder)
    _TONES.clear()
    p, sink = _player(["/m/a.mp3", "/m/b.mp3"])
    try:
        start = time.monotonic()
        assert _wait_for(lambda: p.status()["track"] == "b.mp3")
        assert _wait_for(lambda: p.status()["track"] == "a.mp3")  # round again
        took = time.monotonic() - start
        # at the pace it plays: half a second of tracks took about half a second, written in whole samples
        assert 0.4 < took < 1.5 and len(sink.written) % 4 == 0
        assert 0.3 < len(sink.written) / music.PER_SECOND < took + 0.3
        values = set(array("h", bytes(sink.written)))
        assert {1000, 2000} <= values

        p.next()
        assert _wait_for(lambda: p.status()["track"] == "b.mp3")
        p.back()  # in its first seconds: the one before
        assert _wait_for(lambda: p.status()["track"] == "a.mp3")

        p.pause()  # silence, holding its place
        time.sleep(0.1)
        before = len(sink.written)
        time.sleep(0.2)
        assert set(array("h", bytes(sink.written[before:]))) == {0} and p.status()["playing"] is False
        p.play()
        assert _wait_for(lambda: p.status()["playing"] and set(array("h", bytes(sink.written[-music.CHUNK:]))) - {0})

        p.settings(on=True, shuffle=False, volume=50)  # a quarter as loud (squared)
        time.sleep(0.15)
        assert set(array("h", bytes(sink.written[-music.CHUNK:]))) <= {0, 250, 500}
        p.settings(on=False, shuffle=False, volume=50)  # off: silence
        time.sleep(0.15)
        assert set(array("h", bytes(sink.written[-music.CHUNK:]))) == {0}
    finally:
        p.stop()


def test_the_music_with_no_tracks_is_silence_and_shuffles_each_round(monkeypatch):
    from array import array

    from app.services.live_stream import music

    monkeypatch.setattr(music, "decoder", _fake_decoder)
    _TONES.clear()
    p, sink = _player([])
    try:
        assert _wait_for(lambda: len(sink.written) > music.CHUNK * 5)
        assert set(array("h", bytes(sink.written))) == {0} and p.status()["track"] is None
    finally:
        p.stop()
    # shuffled: each round every track once, in a new order
    rounds = []
    p = music.Player("ffmpeg", lambda: [f"/m/{i}.mp3" for i in range(8)], on=False, shuffle=True, volume=100)  # (off: nothing decoded meanwhile)
    try:
        for _ in range(6):
            rounds.append([p._next_track() for _ in range(8)])
    finally:
        p.stop()
    assert all(sorted(r) == sorted(f"/m/{i}.mp3" for i in range(8)) for r in rounds) and len({tuple(r) for r in rounds}) > 1
