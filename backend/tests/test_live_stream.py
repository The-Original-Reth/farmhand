"""The Stream page: cameras sent live to YouTube or Twitch by ffmpeg, the stream key kept to Farmhand."""
from __future__ import annotations

import os
import threading
import time

import httpx
import pytest

from app.services import live_stream, youtube_live

KEY = "abcd-efgh-ijkl-mnop-qrst"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 40


def _cam(**kw):
    cam = {"name": "Bed", "enabled": True, "service": "mjpegstreamer", "stream_url": "/webcam/?action=stream",
           "snapshot_url": "/webcam/?action=snapshot", "rotation": 0}
    return {**cam, **kw}


class FakeFfmpeg:
    """ffmpeg as the stream starts it: remembers each command, says `lines` on stderr, runs until ended."""

    def __init__(self, lines=(), exits=False):
        self.commands: list[list[str]] = []
        self.lines = list(lines)
        self.exits = exits

    def __call__(self, args):
        self.commands.append(args)
        return _Proc(self.lines, self.exits)


class _Proc:
    def __init__(self, lines, exits):
        self._ended = threading.Event()
        if exits:
            self._ended.set()
        self.stderr = iter([line + "\n" for line in lines])

    def poll(self):
        return 1 if self._ended.is_set() else None

    def wait(self, timeout=None):
        self._ended.wait(timeout)
        return 1

    def terminate(self):
        self._ended.set()

    kill = terminate


@pytest.fixture(autouse=True)
def _fresh():
    from app.services import stream_media

    youtube_live.reset()
    stream_media.forget()  # what the stream folder held is remembered between looks; each test reads its own
    yield
    live_stream.stream.stop()
    youtube_live.reset()


@pytest.fixture()
def ffmpeg(monkeypatch):
    fake = FakeFfmpeg()
    monkeypatch.setattr(live_stream.runner, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(live_stream.runner, "popen", fake)
    return fake


def _wait_for(check, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


def _graph(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_settings_are_saved_and_the_key_never_comes_back(klipper):
    api, _ = klipper
    page = api.get("/stream").json()
    assert page["settings"] == {
        "destination": "youtube", "cols": 1, "rows": 1, "cells": [None], "cameras": [], "show_status": True, "layout": "grid",
        "resolution": "1080p", "seconds_all": 30, "seconds_each": 20, "border_color": "#000000", "background": "#000000", "font": "play", "color": "#FFFFFF", "enabled": True, "title": "",
        "description": "", "key_set": False,
    }
    assert [r["key"] for r in page["resolutions"]] == ["720p", "1080p", "1440p"] and page["resolutions"][2]["label"].startswith("2K")
    assert (page["media"]["images"], page["media"]["slideshows"], page["media"]["error"]) == ([], [], None)
    assert page["status"]["live"] is False
    assert [d["key"] for d in page["destinations"]] == ["youtube", "twitch"]
    assert page["youtube"] == {"client_set": False, "client_id": None, "signed_in": False, "channel": None, "signing_in": None, "error": None}

    # a list of cameras makes a grid just big enough for them
    r = api.put("/stream", json={"stream_key": KEY, "cameras": ["1:Bed", "1:Bed", "1:Nozzle", "2:Camera"], "show_status": False,
                                 "layout": "cycle", "seconds_all": 0, "seconds_each": 45, "title": "  The farm, live ", "description": "Voron prints"})
    assert r.status_code == 200
    s = r.json()["settings"]
    assert (s["cols"], s["rows"], s["cells"]) == (2, 2, [{"camera": "1:Bed"}, {"camera": "1:Nozzle"}, {"camera": "2:Camera"}, None])
    assert (s["cameras"], s["show_status"], s["layout"], s["seconds_all"], s["seconds_each"], s["title"], s["description"], s["key_set"]) == (
        ["1:Bed", "1:Nozzle", "2:Camera"], False, "cycle", 0, 45, "The farm, live", "Voron prints", True)
    assert KEY not in r.text and KEY not in api.get("/stream").text

    # a grid of any size, its squares placed as wanted; the cameras go in square order
    cells = [None, {"camera": "2:Camera"}, None, None, None, {"camera": "1:Bed"}]
    s = api.put("/stream", json={"cols": 3, "rows": 2, "cells": cells, "border_color": "#ff8800"}).json()["settings"]
    assert (s["cols"], s["rows"], s["cells"], s["cameras"], s["border_color"]) == (3, 2, cells, ["2:Camera", "1:Bed"], "#FF8800")

    # a blank key leaves the saved one; clear_key forgets it
    assert api.put("/stream", json={"stream_key": "", "destination": "twitch"}).json()["settings"]["key_set"] is True
    s = api.put("/stream", json={"clear_key": True}).json()["settings"]
    assert s["key_set"] is False and s["destination"] == "twitch" and s["layout"] == "cycle"


def test_settings_from_before_the_grid_become_one(klipper):
    """A list of cameras saved before there was a grid comes back as the grid it made."""
    import json

    from app.services import app_settings

    api, _ = klipper
    db = _db(api)
    app_settings.put(db, live_stream.SETTINGS_KEY, json.dumps({"cameras": ["1:a", "1:b", "1:c", "1:d", "1:e"], "layout": "cycle"}))
    db.commit()
    s = api.get("/stream").json()["settings"]
    assert (s["cols"], s["rows"], len(s["cells"]), s["cameras"]) == (3, 2, 6, ["1:a", "1:b", "1:c", "1:d", "1:e"])


def test_what_cant_be_saved_says_why(klipper):
    api, _ = klipper
    assert "stream key" in api.put("/stream", json={"stream_key": "not a key!"}).json()["detail"]
    assert api.put("/stream", json={"destination": "facebook"}).status_code == 422
    assert api.put("/stream", json={"cameras": ["Bed"]}).status_code == 422
    assert "up to 25" in api.put("/stream", json={"cameras": [f"1:Cam {i}" for i in range(26)]}).json()["detail"]
    assert api.put("/stream", json={"layout": "mosaic"}).status_code == 422
    assert "3 to 3600" in api.put("/stream", json={"seconds_each": 1}).json()["detail"]
    assert "0 to 3600" in api.put("/stream", json={"seconds_all": -1}).json()["detail"]
    assert "100 characters" in api.put("/stream", json={"title": "x" * 101}).json()["detail"]
    assert "< or >" in api.put("/stream", json={"description": "a <b> c"}).json()["detail"]
    assert "1 to 5" in api.put("/stream", json={"cols": 6, "rows": 1, "cells": [None] * 6}).json()["detail"]
    assert "each of the grid's 4 squares" in api.put("/stream", json={"cols": 2, "rows": 2, "cells": [None]}).json()["detail"]
    assert "one square" in api.put("/stream", json={"cols": 2, "rows": 1, "cells": [{"camera": "1:a"}, {"camera": "1:a"}]}).json()["detail"]
    assert "not both" in api.put("/stream", json={"cols": 1, "rows": 1, "cells": [{"image": "a.png", "slideshow": "b"}]}).json()["detail"]
    assert "name a picture" in api.put("/stream", json={"cols": 1, "rows": 1, "cells": [{"image": "../x.png"}]}).json()["detail"]
    assert "up to 500" in api.put("/stream", json={"cols": 1, "rows": 1, "cells": [{"text": "x" * 501}]}).json()["detail"]
    assert "3 to 3600" in api.put("/stream", json={"cols": 1, "rows": 1, "cells": [{"slideshow": "s", "seconds": 2}]}).json()["detail"]
    assert "can hold" in api.put("/stream", json={"cols": 1, "rows": 1, "cells": [{"logo": 9}]}).json()["detail"]
    assert "background colour" in api.put("/stream", json={"background": "blue"}).json()["detail"]
    assert api.put("/stream", json={"background": "#102030"}).json()["settings"]["background"] == "#102030"
    assert "colour" in api.put("/stream", json={"border_color": "red"}).json()["detail"]


def test_going_live_needs_a_key_cameras_and_ffmpeg(klipper, moonraker, monkeypatch):
    api, pid = klipper
    moonraker.webcams = [_cam()]
    assert "stream key" in api.post("/stream/start").json()["detail"]
    api.put("/stream", json={"stream_key": KEY})
    assert "at least one camera in the grid" in api.post("/stream/start").json()["detail"]
    api.put("/stream", json={"cameras": [f"{pid}:Bed"]})
    monkeypatch.setattr(live_stream.runner, "ffmpeg_path", lambda: None)
    r = api.post("/stream/start")
    assert r.status_code == 422 and "ffmpeg" in r.json()["detail"]


def test_going_live_sends_the_chosen_cameras_to_youtube(klipper, moonraker, ffmpeg):
    api, pid = klipper
    moonraker.webcams = [_cam(), _cam(name="Nozzle", rotation=180)]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed", f"{pid}:Nozzle"], "show_status": False})
    r = api.post("/stream/start")
    assert r.status_code == 200, r.text
    status = r.json()["status"]
    assert status["live"] is True and status["destination"] == "youtube"
    assert status["cameras"] == ["VT 1190 · Bed", "VT 1190 · Nozzle"]
    assert status["title"] is None  # no title or description chosen: YouTube's own is left alone
    assert KEY not in r.text
    assert _wait_for(lambda: ffmpeg.commands)
    cmd = ffmpeg.commands[0]
    assert cmd[-1] == f"rtmps://a.rtmps.youtube.com/live2/{KEY}"
    assert cmd.count("-i") == 3  # two cameras and the silent sound track
    assert "http://10.0.6.21/webcam/?action=stream" in cmd
    graph = _graph(cmd)
    assert "xstack=inputs=2:layout=0_0|960_0" in graph and "scale=1920:1080" in graph  # 1080p unless chosen otherwise
    assert "hflip,vflip" in graph  # the Nozzle camera turned round, as Mainsail shows it
    assert "drawtext" not in graph and "overlay" not in graph  # no words, no turns, no logo

    assert api.post("/stream/stop").json()["status"]["live"] is False


def test_progress_is_written_under_each_camera(klipper, moonraker, ffmpeg):
    api, pid = klipper
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "destination": "twitch"})
    assert api.post("/stream/start").status_code == 200
    assert _wait_for(lambda: ffmpeg.commands)
    cmd = ffmpeg.commands[0]
    assert cmd[-1].startswith("rtmps://live.twitch.tv/app/")
    graph = _graph(cmd)
    assert "drawtext=" in graph and "reload=1" in graph and "expansion=none" in graph and "xstack" not in graph


def test_saving_while_live_starts_again_with_the_new_picture(klipper, moonraker, ffmpeg):
    api, pid = klipper
    moonraker.webcams = [_cam(), _cam(name="Nozzle")]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False})
    api.post("/stream/start")
    assert _wait_for(lambda: len(ffmpeg.commands) == 1)
    api.put("/stream", json={"cameras": [f"{pid}:Bed", f"{pid}:Nozzle"], "layout": "cycle"})
    assert _wait_for(lambda: len(ffmpeg.commands) == 2)
    cmd = ffmpeg.commands[1]
    assert "streamselect@pick=inputs=2" in _graph(cmd)
    turns = _graph(cmd).split("sendcmd=f=")[1].split("[")[0].replace("\\:", ":")
    assert turns.endswith("turns.txt")
    api.put("/stream", json={"title": "Just the title"})  # not the picture: ffmpeg carries on
    time.sleep(0.2)
    assert len(ffmpeg.commands) == 2


def test_taking_turns_enlarges_only_the_camera_on_screen():
    srcs = [live_stream.Source(i, f"P{i}", ["-i", f"http://cam{i}"]) for i in range(3)]
    assert live_stream.windows(3, 30, 20) == (90, [(30, 50), (50, 70), (70, 90)])
    look = live_stream.Look(status_files=["/s/0.txt", "/s/1.txt", "/s/2.txt"], cycle=(30, 20), turns_file="/s/turns.txt")
    cmd = live_stream.command("ffmpeg", srcs, "rtmps://x/", look)
    graph = _graph(cmd)
    assert "split=2[g0][s0]" in graph and "xstack=inputs=4" in graph  # 3 cameras in a 2x2 grid, one square empty
    # every camera's picture goes to the switch with its words on, and only what comes through is made full size
    assert "[s1]drawtext=" in graph and "fontsize=h/26" in graph
    assert "[w0][w1][w2]streamselect@pick=inputs=3:map=0,scale=1920:1080" in graph
    assert graph.count("scale=1920:1080") == 2  # the grid once, the camera on screen once: never one per camera
    assert "[grid][full]streamselect@view=inputs=2:map=0[turns]" in graph and "[turns]sendcmd=f=/s/turns.txt[timed]" in graph
    assert cmd[cmd.index("-map") + 1] == "[timed]" and "overlay" not in graph
    assert cmd[cmd.index("-t") + 1] == str(live_stream.TURNS_FOR)  # the day's timetable done, it's started again

    # never the whole grid: no grid made at all, only the camera switch
    graph = _graph(live_stream.command("ffmpeg", srcs, "rtmps://x/", live_stream.Look(cycle=(0, 10), turns_file="/s/turns.txt")))
    assert "xstack" not in graph and "split" not in graph and "streamselect@view" not in graph
    assert "[s0][s1][s2]streamselect@pick=inputs=3:map=0," in graph and "[full]null[turns];[turns]sendcmd=f=/s/turns.txt[timed]" in graph
    # one camera: nothing to take turns with
    cmd = live_stream.command("ffmpeg", srcs[:1], "rtmps://x/", live_stream.Look(cycle=(30, 20)))
    assert "streamselect" not in _graph(cmd) and "[grid]" in _graph(cmd) and "-t" not in cmd


def test_the_squares_of_the_grid():
    srcs = [live_stream.Source(i, f"P{i}", ["-i", f"http://cam{i}"]) for i in range(2)]
    # 3x2: a picture top left, camera 1 in the middle, camera 0 bottom right, the rest empty; a red border round each,
    # on a dark blue stream
    cells = [("card", {"pictures": ["/s/elves.png"], "background": None}), ("camera", 1), None, None, None, ("camera", 0)]
    look = live_stream.Look(cols=3, rows=2, cells=cells, border_color="#FF0000", background="#000033", resolution="720p")
    cmd = live_stream.command("ffmpeg", srcs, "rtmps://x/", look)
    graph = _graph(cmd)
    assert "/s/elves.png" in cmd and cmd[cmd.index("/s/elves.png") - 2] == "1"  # read once a second, not 15 times
    assert "color=c=0x000033:s=426x360:r=15,setsar=1[c0b]" in graph  # the card on the stream's colour
    assert "[3:v]scale=420:354:force_original_aspect_ratio=decrease,setsar=1,fps=15[c0i0];[c0b][c0i0]overlay=(W-w)/2:(H-h)/2[c0o0]" in graph
    assert "color=c=0x000033:s=426x360:r=15" in graph and "pad=426:360:(ow-iw)/2:(oh-ih)/2:color=0x000033" in graph  # empty, round cameras
    assert graph.count("drawbox=x=0:y=0:w=iw:h=ih:color=0xFF0000:t=3") == 6  # every square has its border
    assert "[c0][c1][c2][c3][c4][c5]xstack=inputs=6:layout=0_0|426_0|852_0|0_360|426_360|852_360:fill=0x000033" in graph
    square = {p[:4]: p for p in graph.split(";") if p.startswith("[g")}  # each camera's chain into its square
    assert square["[g1]"].startswith("[g1]scale=426:360") and square["[g1]"].endswith("[c1]")  # camera 1 in the second square
    assert square["[g0]"].endswith("[c5]")  # camera 0 in the last
    # 1x1: the one square is the whole picture
    one = _graph(live_stream.command("ffmpeg", srcs[:1], "u", live_stream.Look(cols=1, rows=1, cells=[("camera", 0)])))
    assert "xstack" not in one and "[c0]scale=1920:1080" in one


def test_the_resolution(klipper, moonraker, ffmpeg):
    api, pid = klipper
    assert "720p, 1080p or 2K" in api.put("/stream", json={"resolution": "4k"}).json()["detail"]
    moonraker.webcams = [_cam(), _cam(name="Nozzle")]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed", f"{pid}:Nozzle"], "resolution": "1080p"})
    api.post("/stream/start")
    assert _wait_for(lambda: ffmpeg.commands)
    cmd = ffmpeg.commands[0]
    graph = _graph(cmd)
    assert "xstack=inputs=2:layout=0_0|960_0" in graph and "scale=1920:1080" in graph
    assert cmd[cmd.index("-b:v") + 1] == "4500k" and cmd[cmd.index("-bufsize") + 1] == "9000k"
    assert "fontsize=30" in graph  # 20 px in a quarter of a 720p picture, in step on 1080p
    # 2K: changing it while live starts the stream again at the new size
    api.put("/stream", json={"resolution": "1440p"})
    assert _wait_for(lambda: len(ffmpeg.commands) == 2)
    cmd = ffmpeg.commands[1]
    assert "scale=2560:1440" in _graph(cmd) and cmd[cmd.index("-b:v") + 1] == "9000k"
    assert "t=6" in _graph(cmd)  # the borders in step too: 3 px on 720p


def test_the_timetable_of_turns():
    assert live_stream.timetable(2, 30, 20, horizon=140).splitlines() == [
        "0 streamselect@view map 0;",
        "30 streamselect@view map 1, streamselect@pick map 0;",
        "50 streamselect@view map 1, streamselect@pick map 1;",
        "70 streamselect@view map 0;",
        "100 streamselect@view map 1, streamselect@pick map 0;",
        "120 streamselect@view map 1, streamselect@pick map 1;",
    ]
    assert live_stream.timetable(3, 0, 10, horizon=30).splitlines() == [
        "0 streamselect@pick map 0;", "10 streamselect@pick map 1;", "20 streamselect@pick map 2;",
    ]
    # a day of the quickest turns of the most cameras stays a small file
    assert len(live_stream.timetable(16, 0, 3).splitlines()) == 24 * 3600 // 3


def test_cards_in_the_picture():
    srcs = [live_stream.Source(0, "P0", ["-i", "http://cam0"])]
    words = {"words": "/s/text-1.txt", "color": "#FFFF00"}
    cells = [("camera", 0),
             ("card", {"background": "#202060", **words, "text_box": {"x": 0.5, "y": 0.5, "size": 0.2}}),  # words on a colour
             ("card", {"pictures": ["/s/a.png", "/s/b.png", "/s/c.jpg"], "seconds": 5, **words, "band": True,
                       "text_box": {"x": 0.25, "y": 0.9, "size": 0.2}}),  # a slideshow, words low on the left
             ("card", {"pictures": ["/s/only.png"]})]  # a picture, no words
    cmd = live_stream.command("ffmpeg", srcs, "u", live_stream.Look(cols=2, rows=2, cells=cells, resolution="720p"))
    graph = _graph(cmd)
    # words in the middle of their colour, plain; at the foot of a slideshow, on a dark band
    assert "color=c=0x202060:s=640x360:r=15,setsar=1[c1b]" in graph and "textfile=/s/text-1.txt" in graph
    assert "fontcolor=0xFFFF00" in graph and "fontsize=72" in graph
    first, second = graph.split("drawtext=")[1], graph.split("drawtext=")[2]
    assert "x=320-text_w/2:y=180-text_h/2" in first and "box=1" not in first
    assert "x=160-text_w/2:y=324-text_h/2" in second and "box=1:boxcolor=black@0.5" in second
    # each picture its own input, read and fitted once a second; the first over the colour, each other over it in its seconds
    assert [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"][2:] == ["/s/a.png", "/s/b.png", "/s/c.jpg", "/s/only.png"]
    assert "[c2o0][c2i1]overlay=(W-w)/2:(H-h)/2:enable='gte(mod(t,15),5)*lt(mod(t,15),10)'[c2o1]" in graph
    assert "[c2o1][c2i2]overlay=(W-w)/2:(H-h)/2:enable='gte(mod(t,15),10)*lt(mod(t,15),15)'[c2o2]" in graph
    assert "[c3b][c3i0]overlay=(W-w)/2:(H-h)/2[c3o0];[c3o0]drawbox" in graph
    assert "sendcmd" not in graph and "-t" not in cmd  # nothing needs a timetable


def test_a_cards_picture_in_its_own_box():
    # the picture fitted into the right half's lower part, a quarter of the square high, inside its 3 px border
    cells = [("card", {"pictures": ["/s/a.png"], "picture_box": {"x": 0.5, "y": 0.75, "w": 0.5, "h": 0.25}})]
    graph = _graph(live_stream.command("ffmpeg", [], "u", live_stream.Look(cols=1, rows=1, cells=cells, resolution="720p")))
    assert "scale=637:178:force_original_aspect_ratio=decrease" in graph
    assert "overlay=640+(637-w)/2:539+(178-h)/2[c0o0]" in graph


def test_card_boxes_are_kept_inside_the_square():
    cell = live_stream._cell({"text": "Hi", "picture_box": {"x": 0.9, "y": -1, "w": 0.5, "h": 0.01}, "text_box": {"x": 3, "y": "no", "size": 9}})
    assert cell["picture_box"] == {"x": 0.5, "y": 0.0, "w": 0.5, "h": 0.05}
    assert cell["text_box"] == {"x": 1.0, "y": 0.5, "size": 0.6}


def test_a_camera_square_with_its_own_background():
    assert live_stream._cell({"camera": "1:Bed", "background": "#00ff00"}) == {"camera": "1:Bed", "background": "#00FF00"}
    assert live_stream._cell({"camera": "1:Bed", "background": "nope"}) == {"camera": "1:Bed"}  # none: the stream's
    srcs = [live_stream.Source(0, "P0", ["-i", "http://cam0"]), live_stream.Source(1, "P1", ["-i", "http://cam1"])]
    cells = [("camera", 0, "#00FF00"), ("camera", 1)]
    graph = _graph(live_stream.command("ffmpeg", srcs, "u", live_stream.Look(cols=2, rows=1, cells=cells, resolution="720p", background="#112233")))
    assert "[g0]scale=640:720:force_original_aspect_ratio=decrease,pad=640:720:(ow-iw)/2:(oh-ih)/2:color=0x00FF00" in graph
    assert "[g1]scale=640:720:force_original_aspect_ratio=decrease,pad=640:720:(ow-iw)/2:(oh-ih)/2:color=0x112233" in graph


def _png(color=b"r"):
    return PNG + color


def test_the_stream_folder(klipper, moonraker, ffmpeg, tmp_path):
    from app.services import stream_media

    api, pid = klipper
    loc = api.get("/stream/location").json()
    assert loc["is_default"] is True and loc["path"].replace("\\", "/").endswith("/stream")
    # pictures: uploaded into images/, named after their files, a second of the same name numbered
    r = api.post("/stream/pictures", files=[("files", ("Elves.png", _png(), "image/png")), ("files", ("elves.png", _png(b"2"), "image/png"))])
    assert r.status_code == 201 and r.json()["media"]["images"] == ["elves (2).png", "Elves.png"]  # in name order, any case
    assert "PNG, JPEG or WebP" in api.post("/stream/pictures", files=[("files", ("x.gif", b"GIF89a", "image/gif"))]).json()["detail"]
    got = api.get("/stream/pictures/Elves.png")
    assert got.content == _png() and got.headers["content-type"] == "image/png"
    assert api.get("/stream/pictures/nope.png").status_code == 404
    # a picture dropped in by hand counts too, once the folder is scanned: looking at the page doesn't read it again
    root = stream_media.folder(_db(api))
    (root / "images" / "Dropped.jpg").write_bytes(b"\xff\xd8\xff..")
    assert "Dropped.jpg" not in api.get("/stream").json()["media"]["images"]
    assert "Dropped.jpg" in api.post("/stream/scan").json()["media"]["images"]

    # slideshows: a folder each, pictures added in name order
    assert api.post("/stream/slideshows", json={"name": "Prints"}).status_code == 201
    assert "already a slideshow" in api.post("/stream/slideshows", json={"name": "prints"}).json()["detail"]
    files = [("files", ("10 frog.png", _png(b"f"), "image/png")), ("files", ("2 benchy.png", _png(b"b"), "image/png"))]
    shows = api.post("/stream/slideshows/Prints/pictures", files=files).json()["media"]["slideshows"]
    assert shows == [{"name": "Prints", "images": ["2 benchy.png", "10 frog.png"]}]
    assert api.get("/stream/slideshows/Prints/pictures/10 frog.png").content == _png(b"f")

    # going live: a slideshow with words over it, read straight from the stream folder
    moonraker.webcams = [_cam()]
    cells = [{"camera": f"{pid}:Bed"}, {"slideshow": "Prints", "seconds": 4, "text": " Live! ", "text_box": {"x": 0.5, "y": 0.1}}, {"image": "Elves.png"},
             {"image": "gone.png", "background": "#123456"}]
    s = api.put("/stream", json={"stream_key": KEY, "cols": 2, "rows": 2, "cells": cells, "show_status": False}).json()["settings"]
    assert s["cells"][1] == {"background": None, "image": None, "slideshow": "Prints", "seconds": 4, "text": "Live!", "color": None, "font": None, "band": False,
                             "picture_box": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "text_box": {"x": 0.5, "y": 0.1, "size": 0.125}}
    api.post("/stream/start")
    assert _wait_for(lambda: ffmpeg.commands)
    cmd = ffmpeg.commands[0]
    inputs = [cmd[i + 1].replace("\\", "/") for i, a in enumerate(cmd) if a == "-i"][2:]
    assert [p.split("/stream/")[1] for p in inputs] == ["slideshows/Prints/2 benchy.png", "slideshows/Prints/10 frog.png", "images/Elves.png"]
    assert "color=c=0x123456" in _graph(cmd)  # a picture that isn't there: just its colour
    text = _graph(cmd).split("textfile=")[1].split(":reload")[0].replace("\\:", ":")
    with open(text, encoding="utf-8") as f:
        assert f.read() == "Live!"

    # deleting a slideshow picture starts the stream again; deleting the slideshow removes its folder
    assert api.delete("/stream/slideshows/Prints/pictures/2 benchy.png").status_code == 409
    api.delete("/stream/slideshows/Prints/pictures/2 benchy.png?confirm=true")
    assert _wait_for(lambda: len(ffmpeg.commands) == 2)
    assert api.delete("/stream/slideshows/Prints?confirm=true").json()["media"]["slideshows"] == []
    assert not (root / "slideshows" / "Prints").exists()
    assert api.delete("/stream/slideshows/Prints?confirm=true").status_code == 404
    # a slideshow folder holding something else is emptied of pictures and left
    (root / "slideshows" / "Mixed").mkdir()
    (root / "slideshows" / "Mixed" / "a.png").write_bytes(_png())
    (root / "slideshows" / "Mixed" / "notes.txt").write_text("keep me")
    assert "other files" in api.delete("/stream/slideshows/Mixed?confirm=true").json()["detail"]
    assert sorted(p.name for p in (root / "slideshows" / "Mixed").iterdir()) == ["notes.txt"]


def test_choosing_the_stream_folder(klipper, share):
    api, _ = klipper
    r = api.put("/stream/location", json={"path": str(share)})
    assert r.status_code == 200 and r.json()["is_default"] is False and r.json()["status"]["ready"] is True
    api.post("/stream/pictures", files=[("files", ("a.png", _png(), "image/png"))])
    assert (share / "images" / "a.png").is_file()
    assert api.put("/stream/location", json={"path": None}).json()["is_default"] is True


def test_a_camera_that_only_plays_in_a_browser_is_refused(klipper, moonraker, ffmpeg):
    api, pid = klipper
    moonraker.webcams = [_cam(service="webrtc-janus", stream_url="/janus/")]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"]})
    r = api.post("/stream/start")
    assert r.status_code == 422 and "WebRTC" in r.json()["detail"]
    api.put("/stream", json={"cameras": [f"{pid}:Gone"]})
    assert "can't be reached" in api.post("/stream/start").json()["detail"]
    api.put("/stream", json={"cameras": ["999:Bed"]})
    assert "printer is gone" in api.post("/stream/start").json()["detail"]


def test_camera_streamer_is_read_as_mjpeg_and_a_buddy3d_over_rtsp(db_session):
    from app.models.printer_camera import PrinterCamera
    from tests import factories

    p = factories.klipper_printer(db_session)
    cam = {"name": "Cam", "service": "webrtc-camerastreamer", "mjpeg": False, "stream_url": "http://10.0.6.21/webcam/webrtc"}
    assert live_stream.input_args(p, cam)[-1] == "http://10.0.6.21/webcam/stream"
    p.camera_row = PrinterCamera(address="10.0.6.40")
    assert live_stream.input_args(p, {"name": "Camera", "service": "farmhand-go2rtc"})[-1] == "rtsp://10.0.6.40/live"
    # Mainsail's adaptive MJPEG shows snapshots in the browser, but its address is the MJPEG stream itself
    adaptive = {"name": "front", "service": "mjpegstreamer-adaptive", "mjpeg": False, "stream_url": "http://10.0.6.21/webcam/?action=stream"}
    assert live_stream.input_args(p, adaptive) == ["-f", "mpjpeg", "-i", "http://10.0.6.21/webcam/?action=stream"]
    # go2rtc on the printer: the same camera over its RTSP port
    go2rtc = {"name": "Chamber", "service": "webrtc-go2rtc", "mjpeg": False, "stream_url": "http://10.0.6.33:1984/stream.html?src=chamber&mode=webrtc"}
    assert live_stream.input_args(p, go2rtc) == ["-rtsp_transport", "tcp", "-i", "rtsp://10.0.6.33:8554/chamber"]


def test_when_ffmpeg_stops_it_says_why_without_the_key(klipper, moonraker, monkeypatch):
    api, pid = klipper
    moonraker.webcams = [_cam()]
    fake = FakeFfmpeg(lines=[f"rtmps://a.rtmps.youtube.com/live2/{KEY}: Input/output error"], exits=True)
    monkeypatch.setattr(live_stream.runner, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(live_stream.runner, "popen", fake)
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False})
    api.post("/stream/start")
    assert _wait_for(lambda: live_stream.stream.status()["error"])
    error = api.get("/stream").json()["status"]["error"]
    assert "Input/output error" in error and "<stream key>" in error and KEY not in error
    assert api.get("/stream").json()["status"]["live"] is True  # still meant to be live: it's tried again


def test_the_grid_and_the_words():
    assert live_stream.grid(1, 1280, 720) == (1, 1, 1280, 720)
    assert live_stream.grid(3, 1280, 720) == (2, 2, 640, 360)
    assert live_stream.grid(5, 1280, 720) == (3, 2, 426, 360)
    assert live_stream.grid(4) == (2, 2, 960, 540)  # 1080p unless chosen otherwise
    assert live_stream.auto_grid(0) == (1, 1) and live_stream.auto_grid(7) == (3, 3) and live_stream.auto_grid(25) == (5, 5)
    assert live_stream.status_line("VT 1190", {"state": "printing", "progress": 41.6, "file": "jobs/benchy.gcode"}) == "VT 1190 · Printing 42% · benchy.gcode"
    assert live_stream.status_line("VT 1190", {"state": "paused", "progress": None, "file": None}) == "VT 1190 · Paused"
    assert live_stream.status_line("VT 1190", {"state": None}) == "VT 1190 · Idle"
    assert live_stream.status_line("Prusa_2", {"state": None, "error": "PrusaLink refused the login."}) == "Prusa_2 · Status unknown"


def test_stream_settings_stay_out_of_the_settings_copy():
    from app import change_hooks

    assert change_hooks._what_changed("/stream") is None
    assert change_hooks._what_changed("/stream/start") is None


# ------------------------------------------------------------------ YouTube: signing in, the title and description

CLIENT_ID = "1234-abcd.apps.googleusercontent.com"
SECRET = "GOCSPX-secret_value"


class FakeGoogle:
    """Google's sign-in for devices and the bits of the YouTube Data API Farmhand uses."""

    def __init__(self):
        self.entered = False  # the code typed in at google.com/device
        self.denied = False
        self.broadcasts: list[dict] = []
        self.videos: dict[str, dict] = {}
        self.revoked: list[str] = []
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        form = dict(httpx.QueryParams(request.content.decode())) if request.method == "POST" else {}
        if url == youtube_live.DEVICE_URL:
            if form.get("client_id") != CLIENT_ID:
                return httpx.Response(401, json={"error": "invalid_client", "error_description": "The OAuth client was not found."})
            return httpx.Response(200, json={"device_code": "dev-1", "user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device",
                                             "expires_in": 1800, "interval": 0})
        if url == youtube_live.TOKEN_URL:
            if form.get("grant_type") == youtube_live.DEVICE_GRANT:
                if self.denied:
                    return httpx.Response(403, json={"error": "access_denied"})
                if not self.entered:
                    return httpx.Response(428, json={"error": "authorization_pending"})
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3599})
            if form.get("refresh_token") == "rt-1" and form.get("client_secret") == SECRET:
                return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3599})
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
        if url.startswith(youtube_live.REVOKE_URL):
            self.revoked.append(form.get("token"))
            return httpx.Response(200, json={})
        if request.headers.get("authorization") not in ("Bearer at-1", "Bearer at-2"):
            return httpx.Response(401, json={"error": {"code": 401, "message": "Invalid Credentials"}})
        path = request.url.path.removeprefix("/youtube/v3")
        if path == "/channels":
            return httpx.Response(200, json={"items": [{"snippet": {"title": "3D Printing Elves"}}]})
        if path == "/liveBroadcasts":
            return httpx.Response(200, json={"items": self.broadcasts})
        if path == "/videos" and request.method == "GET":
            vid = request.url.params["id"]
            return httpx.Response(200, json={"items": [{"id": vid, "snippet": self.videos[vid]}] if vid in self.videos else []})
        if path == "/videos" and request.method == "PUT":
            import json

            body = json.loads(request.content)
            self.videos[body["id"]] = body["snippet"]
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": {"code": 404, "message": "Not found"}})


@pytest.fixture()
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(youtube_live, "transport", httpx.MockTransport(fake.handle))
    return fake


def _signed_in(api, google):
    api.put("/stream/youtube", json={"client_id": CLIENT_ID, "client_secret": SECRET})
    api.post("/stream/youtube/sign-in")
    google.entered = True
    return api.get("/stream").json()["youtube"]


def test_signing_in_to_youtube_with_a_code(klipper, google):
    api, _ = klipper
    assert "client ID" in api.post("/stream/youtube/sign-in").json()["detail"]
    assert "client ID" in api.put("/stream/youtube", json={"client_id": "nope", "client_secret": SECRET}).json()["detail"]
    assert "secret too" in api.put("/stream/youtube", json={"client_id": CLIENT_ID}).json()["detail"]
    r = api.put("/stream/youtube", json={"client_id": CLIENT_ID, "client_secret": SECRET})
    assert r.json()["youtube"]["client_set"] is True and SECRET not in r.text

    yt = api.post("/stream/youtube/sign-in").json()["youtube"]
    assert yt["signing_in"] == {"user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device"}
    assert api.get("/stream").json()["youtube"]["signed_in"] is False  # not entered yet: still waiting
    google.entered = True
    yt = api.get("/stream").json()["youtube"]
    assert yt["signed_in"] is True and yt["channel"] == "3D Printing Elves" and yt["signing_in"] is None
    assert "rt-1" not in api.get("/stream").text

    # the same client again, secret left blank: kept, still signed in
    assert api.put("/stream/youtube", json={"client_id": CLIENT_ID}).json()["youtube"]["signed_in"] is True
    yt = api.post("/stream/youtube/sign-out", json={}).json()["youtube"]
    assert yt["signed_in"] is False and yt["client_set"] is True and google.revoked == ["rt-1"]
    assert api.post("/stream/youtube/sign-out", json={"forget_client": True}).json()["youtube"]["client_set"] is False


def test_turning_the_sign_in_down_says_so(klipper, google):
    api, _ = klipper
    api.put("/stream/youtube", json={"client_id": CLIENT_ID, "client_secret": SECRET})
    api.post("/stream/youtube/sign-in")
    google.denied = True
    yt = api.get("/stream").json()["youtube"]
    assert yt["signed_in"] is False and yt["signing_in"] is None and "turned it down" in yt["error"]


def test_the_title_and_description_are_set_on_the_live_broadcast(klipper, google):
    api, _ = klipper
    assert "Sign in to YouTube" in api.post("/stream/youtube/apply").json()["detail"]
    _signed_in(api, google)
    assert "title or description" in api.post("/stream/youtube/apply").json()["detail"]
    api.put("/stream", json={"title": "Farm live", "description": ""})
    assert api.post("/stream/youtube/apply").status_code == 200  # tried; not live, so nothing to show for it
    creds = youtube_live.credentials(_db(api))
    with pytest.raises(youtube_live.YouTubeError) as e:
        youtube_live.set_broadcast_text(creds, "Farm live", "")
    assert e.value.retry is True

    google.broadcasts = [{"id": "vid-9", "snippet": {"title": "Old"}}]
    google.videos["vid-9"] = {"title": "Old", "description": "Kept description", "categoryId": "20", "tags": ["voron"]}
    done = youtube_live.set_broadcast_text(creds, "Farm live", "")
    assert done == {"video_id": "vid-9", "title": "Farm live"}
    assert google.videos["vid-9"] == {"title": "Farm live", "description": "Kept description", "categoryId": "20", "tags": ["voron"]}


def _db(api):
    """The API's own database session (the test client's override), for calling a service directly."""
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


def test_going_live_sets_the_title_once_the_broadcast_is_there(klipper, moonraker, ffmpeg, google, monkeypatch):
    api, pid = klipper
    monkeypatch.setattr(live_stream.runner, "TITLE_EVERY", 0.05)
    moonraker.webcams = [_cam()]
    _signed_in(api, google)
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False, "title": "Farm live",
                             "description": "Printing all day"})
    status = api.post("/stream/start").json()["status"]
    assert status["title"]["state"] == "waiting"
    time.sleep(0.2)
    assert live_stream.stream.status()["title"]["state"] == "waiting"  # no broadcast yet: still trying
    google.broadcasts = [{"id": "vid-1", "snippet": {"title": "Live stream"}}]
    google.videos["vid-1"] = {"title": "Live stream", "description": "", "categoryId": "28"}
    assert _wait_for(lambda: live_stream.stream.status()["title"]["state"] == "done")
    assert google.videos["vid-1"]["title"] == "Farm live" and google.videos["vid-1"]["description"] == "Printing all day"

    # a new title saved while live goes straight to the broadcast, without starting the stream again
    api.put("/stream", json={"title": "Night shift"})
    assert google.videos["vid-1"]["title"] == "Night shift" and len(ffmpeg.commands) == 1


def test_going_live_without_signing_in_says_the_title_wont_be_set(klipper, moonraker, ffmpeg):
    api, pid = klipper
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False, "title": "Farm live"})
    status = api.post("/stream/start").json()["status"]
    assert status["title"]["state"] == "failed" and "Sign in to YouTube" in status["title"]["message"]


def test_a_cards_words_in_the_font_chosen(monkeypatch, tmp_path):
    # a font the server has is used; one it hasn't (or one not in the list) writes in the stream's own font
    (tmp_path / "truetype" / "lato").mkdir(parents=True)
    (tmp_path / "truetype" / "lato" / "Lato-Black.ttf").write_bytes(b"font")
    monkeypatch.setattr(live_stream.fonts, "FONTS_DIR", str(tmp_path))
    assert live_stream._cell({"text": "Hi", "font": "lato-black"})["font"] == "lato-black"
    assert live_stream._cell({"text": "Hi", "font": "wingdings"})["font"] is None  # not one of them: the stream's
    assert live_stream.font_file("lato-black").replace("\\", "/").endswith("truetype/lato/Lato-Black.ttf")
    assert live_stream.font_file("roboto") == live_stream.FONT
    cells = [("card", {"words": "/s/t.txt", "font": "lato-black"})]
    graph = _graph(live_stream.command("ffmpeg", [], "u", live_stream.Look(cols=1, rows=1, cells=cells, resolution="720p")))
    assert "Lato-Black.ttf" in graph


def test_the_stream_folder_as_windows_reaches_it(db_session, monkeypatch, tmp_path):
    from app import mounts
    from app.models import NetworkShare
    from app.services import stream_media

    monkeypatch.setattr(mounts, "mount_point_for", lambda name: tmp_path / name)
    db_session.add(NetworkShare(name="nas", protocol="smb", server="10.0.0.5", share="prints/Farmhand"))
    db_session.add(NetworkShare(name="nfs", protocol="nfs", server="10.0.0.6", share="/export"))
    db_session.commit()
    (tmp_path / "nas" / "stream").mkdir(parents=True)
    (tmp_path / "nfs").mkdir()
    assert stream_media.windows_path(db_session, str(tmp_path / "nas" / "stream")) == "\\\\10.0.0.5\\prints\\Farmhand\\stream"
    assert stream_media.windows_path(db_session, str(tmp_path / "nfs")) is None  # NFS: Windows doesn't reach it that way
    assert stream_media.windows_path(db_session, str(tmp_path / "elsewhere")) is None


def test_a_camera_squares_own_words():
    assert live_stream._cell({"camera": "1:Bed", "show_words": False, "words_size": 0.9, "words_color": "#ff0000", "words_font": "lato"}) == {
        "camera": "1:Bed", "show_words": False, "words_size": 0.3, "words_color": "#FF0000", "words_font": "lato"}
    assert live_stream._cell({"camera": "1:Bed", "show_words": True, "words_color": "#FFFFFF", "words_font": "nope"}) == {"camera": "1:Bed", "words_color": "#FFFFFF"}  # white chosen: kept, as the stream's may be another
    srcs = [live_stream.Source(i, f"P{i}", ["-i", f"http://cam{i}"]) for i in range(3)]
    cells = [("camera", 0, {"camera": "1:A", "show_words": False}),
             ("camera", 1, {"camera": "1:B", "words_size": 0.1, "words_color": "#FF0000"}), ("camera", 2)]
    look = live_stream.Look(cols=3, rows=1, cells=cells, resolution="720p", status_files=["/s/0.txt", "/s/1.txt", "/s/2.txt"], cycle=(10, 5))
    graph = _graph(live_stream.command("ffmpeg", srcs, "u", look))
    tiles = {i: graph.split(f"[g{i}]scale")[1].split(f"[c{i}]")[0] for i in range(3)}
    assert "drawtext" not in tiles[0]  # its words turned off
    assert "fontsize=72:fontcolor=0xFF0000" in tiles[1]  # a tenth of its 720-high square, in red
    assert "fontcolor=0xFFFFFF" in tiles[2]  # as usual
    # on its own, taking turns: the same choices
    assert "[s0]drawtext" not in graph and "[s1]drawtext" in graph and "fontsize=h*0.1:fontcolor=0xFF0000" in graph


def test_play_is_kept_with_farmhand():
    assert live_stream.font_file("play").replace("\\", "/").endswith("app/fonts/Play-Regular.ttf")
    assert os.path.isfile(live_stream.font_file("play-bold"))


def test_the_stream_can_be_turned_off(klipper, moonraker, ffmpeg):
    # the Stream page's switch: off stops a live stream and keeps it from going live; on, it can again
    api, pid = klipper
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"]})
    assert api.post("/stream/start").json()["status"]["live"] is True
    off = api.put("/stream", json={"enabled": False}).json()
    assert off["settings"]["enabled"] is False and off["status"]["live"] is False
    r = api.post("/stream/start")
    assert r.status_code == 422 and "turned off" in r.json()["detail"]
    assert api.put("/stream", json={"enabled": True}).json()["settings"]["enabled"] is True
    assert api.post("/stream/start").json()["status"]["live"] is True
