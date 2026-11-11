"""The Stream page: cameras sent live to YouTube by ffmpeg, the stream key kept to Farmhand."""
from __future__ import annotations

import os
import time

import pytest

from app.services import live_stream

from .factories import api_db as _db, wait_for as _wait_for, webcam as _cam
from .fake_ffmpeg import FakeFfmpeg

pytestmark = pytest.mark.usefixtures("stream_fresh")

KEY = "abcd-efgh-ijkl-mnop-qrst"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 40


def _graph(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_settings_are_saved_and_the_key_never_comes_back(klipper):
    api, _ = klipper
    page = api.get("/stream").json()
    assert page["settings"] == {
        "destination": "youtube", "cols": 1, "rows": 1, "cells": [None], "cameras": [], "show_status": True, "layout": "grid",
        "resolution": "1080p", "seconds_all": 30, "seconds_each": 20, "border_color": "#000000", "background": "#000000", "font": "play", "color": "#FFFFFF", "enabled": True,
        "music": True, "music_volume": 50, "music_shuffle": True, "delay": 60, "title": "", "description": "", "key_set": False,
        "key_from_youtube": False,
        "youtube": {"privacy": "public", "tags": [], "category": "28", "made_for_kids": False, "latency": "normal", "dvr": True,
                    "auto_start": True, "auto_stop": True},
    }
    assert [r["key"] for r in page["resolutions"]] == ["720p", "1080p", "1440p"] and page["resolutions"][2]["label"].startswith("2K")
    assert (page["media"]["images"], page["media"]["slideshows"], page["media"]["music"], page["media"]["error"]) == ([], [], [], None)
    assert page["status"]["live"] is False
    assert [d["key"] for d in page["destinations"]] == ["youtube"]  # (Twitch for later)
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
    assert api.put("/stream", json={"stream_key": "", "destination": "youtube"}).json()["settings"]["key_set"] is True
    s = api.put("/stream", json={"clear_key": True}).json()["settings"]
    assert s["key_set"] is False and s["destination"] == "youtube" and s["layout"] == "cycle"
    # Twitch is gone for now: refused, and a setup saved with it is read as YouTube
    assert "YouTube Live" in api.put("/stream", json={"destination": "twitch"}).json()["detail"]
    import json as _json

    from app.services import app_settings

    db = _db(api)
    raw = _json.loads(app_settings.get(db, live_stream.SETTINGS_KEY))
    app_settings.put(db, live_stream.SETTINGS_KEY, _json.dumps({**raw, "destination": "twitch"}))
    db.commit()
    assert api.get("/stream").json()["settings"]["destination"] == "youtube"


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
    # the picture goes to the relay; the sender holds the connection to YouTube, passing the stream on as it is
    assert cmd[-2:] == ["mpegts", "pipe:1"] and "-output_ts_offset" in cmd
    assert _wait_for(lambda: ffmpeg.senders) and ffmpeg.senders[0][-1] == f"rtmps://a.rtmps.youtube.com/live2/{KEY}"
    assert ffmpeg.senders[0][ffmpeg.senders[0].index("-c") + 1] == "copy" and "-re" in ffmpeg.senders[0]
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
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"]})
    assert api.post("/stream/start").status_code == 200
    assert _wait_for(lambda: ffmpeg.commands)
    cmd = ffmpeg.commands[0]
    assert cmd[-1] == "pipe:1" and _wait_for(lambda: ffmpeg.senders) and ffmpeg.senders[0][-1] == "rtmps://a.rtmps.youtube.com/live2/" + KEY
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
    assert cmd[cmd.index("-b:v") + 1] == "2500k" and cmd[cmd.index("-bufsize") + 1] == "5000k"
    assert "fontsize=30" in graph  # 20 px in a quarter of a 720p picture, in step on 1080p
    # 2K: it takes the new size from the next Go live
    api.put("/stream", json={"resolution": "1440p"})
    api.post("/stream/stop")
    api.post("/stream/start")
    assert _wait_for(lambda: len(ffmpeg.commands) == 2)
    cmd = ffmpeg.commands[1]
    assert "scale=2560:1440" in _graph(cmd) and cmd[cmd.index("-b:v") + 1] == "4500k"
    assert "t=6" in _graph(cmd)  # the borders in step too: 3 px on 720p


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
    assert s["cells"][1] == {"background": None, "image": None, "slideshow": "Prints", "seconds": 4, "text": "Live!", "color": None, "font": None, "band": False, "captions": {}, "picture_boxes": {},
                             "picture_box": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "text_box": {"x": 0.5, "y": 0.1, "size": 0.125},
                             "layers": [], "slide_layers": {}}
    api.post("/stream/start")
    assert _wait_for(lambda: ffmpeg.commands)
    cmd = ffmpeg.commands[0]
    inputs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"][2:]
    # read from the stream's own folder, never the stream folder (on the NAS, pictures being copied in clashed with
    # ffmpeg reading them every second): the slideshow as one input, its screens put together once and listed in
    # order (each for its 4 s), and the single picture from a copy made once
    assert [os.path.basename(p) for p in inputs] == ["list-0.txt", "Elves.png"]
    assert cmd[cmd.index(inputs[0]) - 5:cmd.index(inputs[0])] == ["-f", "concat", "-safe", "0", "-i"] and "-t" in cmd
    assert not any(os.path.realpath(p).startswith(os.path.realpath(root)) for p in inputs)
    listed = open(inputs[0], encoding="utf-8").read().splitlines()
    shots = [os.path.basename(l[len("file '"):-1]) for l in listed if l.startswith("file ")]
    assert shots[0] != shots[1] and shots[:4] == [shots[0], shots[1], shots[0], shots[1]]  # two screens, in turn
    assert listed[2:4] == [listed[2], listed[2]] or "duration 4" in listed[4]
    assert open(inputs[1], "rb").read() == _png()
    (root / "images" / "Elves.png").write_bytes(b"changed while live")
    assert open(inputs[1], "rb").read() == _png()
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


def test_more_pictures_and_text_on_a_card(klipper, moonraker, ffmpeg):
    """A card's more pictures and pieces of text, each placed on its own: kept, checked, and drawn in their order (a
    slideshow screen's only in that screen's seconds), their pictures read from copies."""
    from app.services import stream_media

    api, pid = klipper
    api.post("/stream/pictures", files=[("files", ("Logo.png", _png(b"L"), "image/png")), ("files", ("Frog.png", _png(b"F"), "image/png"))])
    api.post("/stream/slideshows", json={"name": "Prints"})
    api.post("/stream/slideshows/Prints/pictures", files=[("files", ("a.png", _png(b"a"), "image/png")), ("files", ("b.png", _png(b"b"), "image/png"))])
    layers = [
        {"type": "picture", "image": "Logo.png", "box": {"x": 0.6, "y": 0.1, "w": 0.3, "h": 0.3}},
        {"type": "text", "text": "  Frog, 20 hours ", "box": {"x": 0.3, "y": 0.9, "size": 0.06}, "font": "lato", "color": "#ffd54f", "band": True},
        {"type": "picture", "image": "gone.png"},  # not in the stream folder: left out going live
        {"type": "text", "text": "   "},  # no words: left out going live
        {"type": "sticker"},  # not a kind there is: dropped
    ]
    screens = {"b.png": [{"type": "text", "text": "On b", "box": {"x": 0.5, "y": 0.5, "size": 0.1}}],
               "blank:9": [{"type": "picture", "image": "Logo.png"}], "a/b": [{"type": "text", "text": "bad name"}]}
    cells = [{"camera": f"{pid}:Bed"}, {"image": "Frog.png", "layers": layers}, {"slideshow": "Prints", "seconds": 5, "slide_layers": screens}, None]
    s = api.put("/stream", json={"stream_key": KEY, "cols": 2, "rows": 2, "cells": cells, "show_status": False}).json()["settings"]
    kept = s["cells"][1]["layers"]
    assert [x["type"] for x in kept] == ["picture", "text", "picture", "text"]
    assert kept[0] == {"type": "picture", "image": "Logo.png", "box": {"x": 0.6, "y": 0.1, "w": 0.3, "h": 0.3}}
    assert kept[1] == {"type": "text", "text": "Frog, 20 hours", "box": {"x": 0.3, "y": 0.9, "size": 0.06}, "font": "lato", "color": "#FFD54F", "band": True}
    assert kept[2]["box"] == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    assert sorted(s["cells"][2]["slide_layers"]) == ["b.png", "blank:9"] and s["cells"][2]["layers"] == []
    # too many, or too many words, are refused with why
    many = api.put("/stream", json={"cols": 1, "rows": 1, "cells": [{"text": "", "layers": [{"type": "text", "text": "x"}] * 13}]})
    assert many.status_code == 422 and "Up to 12" in many.json()["detail"]
    long = api.put("/stream", json={"cols": 1, "rows": 1, "cells": [{"slideshow": "Prints", "slide_layers": {"a.png": [{"type": "text", "text": "x" * 501}]}}]})
    assert long.status_code == 422 and "“a.png”" in long.json()["detail"] and "500" in long.json()["detail"]

    moonraker.webcams = [_cam()]
    api.post("/stream/start")
    assert _wait_for(lambda: ffmpeg.commands)
    cmd = ffmpeg.commands[0]
    graph = _graph(cmd)
    inputs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]
    root = stream_media.folder(_db(api))
    # the logo read from one copy in the stream's own folder (on the picture card and on the slideshow's blank-less screen)
    logos = [p for p in inputs if os.path.basename(p) == "Logo.png"]
    assert len(logos) == 1 and not os.path.realpath(logos[0]).startswith(os.path.realpath(root))
    # the picture card: its picture, then the logo over it (in its box, kept to its shape), then its own words
    logo_input = inputs.index(logos[0])
    assert f"[{logo_input}:v]scale=" in graph and "[c1o0][c1L0]overlay=" in graph
    layer_text = next(p for p in graph.split(";") if p.startswith("[c1l0]drawtext"))
    from app.services.live_stream.words import filter_path

    assert "fontcolor=0xFFD54F" in layer_text and "box=1" in layer_text and f"fontfile={filter_path(live_stream.font_file('lato'))}:" in layer_text
    with open(layer_text.split("textfile=")[1].split(":reload")[0].replace("\\:", ":"), encoding="utf-8") as f:
        assert f.read() == "Frog, 20 hours"
    card = [p for p in graph.split(";") if p.startswith("[c1")]
    assert "gone.png" not in " ".join(cmd) and sum("drawtext" in p for p in card) == 1  # the one not there, and the empty words: left out
    # the slideshow: b.png's words only in its seconds (the second of two, 5 s each)
    b_words = next(p for p in graph.split(";") if p.startswith("[c2f]drawtext"))
    assert "enable='gte(mod(" in b_words and ",10),5)*lt(mod(" in b_words


def test_a_new_layout_is_handed_over_to_without_dropping_youtube(klipper, moonraker, ffmpeg):
    """While live, a change to the picture starts a new picture ffmpeg beside the old one and hands over to it: the
    connection to YouTube (the sender) is never started again, and the old picture is stopped once the new one has
    taken over. The delay is chosen on the page (0 to 120 s) and said while live."""
    api, pid = klipper
    moonraker.webcams = [_cam(), _cam(name="Nozzle")]
    assert "0 to 120" in api.put("/stream", json={"delay": 121}).json()["detail"]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False, "delay": 5})
    api.post("/stream/start")
    assert _wait_for(lambda: ffmpeg.commands and ffmpeg.senders)
    assert _wait_for(lambda: api.get("/stream").json()["status"]["on_air"])
    delay = api.get("/stream").json()["status"]["delay"]
    assert delay["seconds"] == 5 and delay["filling"] is True  # (nothing has gone to YouTube yet: collecting the 5 s)

    # a new layout: a second picture ffmpeg, the same sender; the first picture stopped once the second took over
    api.put("/stream", json={"cameras": [f"{pid}:Bed", f"{pid}:Nozzle"]})
    assert _wait_for(lambda: len(ffmpeg.commands) == 2)
    assert _wait_for(lambda: ffmpeg.procs[0].poll() is not None)
    assert ffmpeg.procs[1].poll() is None and len(ffmpeg.senders) == 1 and ffmpeg.sender_procs[0].poll() is None
    assert "-output_ts_offset" in ffmpeg.commands[1] and api.get("/stream").json()["status"]["on_air"]
    # and a change of key (another connection) starts afresh, sender too
    api.put("/stream", json={"stream_key": "wxyz-1234-5678-abcd"})
    assert _wait_for(lambda: len(ffmpeg.senders) == 2) and ffmpeg.sender_procs[0].poll() is not None
    assert ffmpeg.senders[1][-1].endswith("wxyz-1234-5678-abcd")
    api.post("/stream/stop")
    assert all(p.poll() is not None for p in ffmpeg.procs + ffmpeg.sender_procs)


def test_a_burst_of_saves_while_live_is_one_hand_over(klipper, moonraker, ffmpeg, monkeypatch):
    """Saves in quick succession while live: each waits a moment for more (SETTLE), so a burst brings one new picture,
    not one each; the page hears a change is on its way meanwhile."""
    api, pid = klipper
    moonraker.webcams = [_cam(), _cam(name="Nozzle")]
    monkeypatch.setattr(live_stream.runner, "SETTLE", 0.6)
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False})
    api.post("/stream/start")
    assert _wait_for(lambda: len(ffmpeg.commands) == 1 and api.get("/stream").json()["status"]["on_air"])
    for cams in ([f"{pid}:Bed", f"{pid}:Nozzle"], [f"{pid}:Nozzle"], [f"{pid}:Nozzle", f"{pid}:Bed"], [f"{pid}:Bed", f"{pid}:Nozzle"]):
        status = api.put("/stream", json={"cameras": cams}).json()["status"]
    assert status["changing"] is True
    assert _wait_for(lambda: len(ffmpeg.commands) == 2)
    time.sleep(1)
    assert len(ffmpeg.commands) == 2 and len(ffmpeg.senders) == 1  # one hand-over, the same connection
    assert _wait_for(lambda: not api.get("/stream").json()["status"]["changing"]) and ffmpeg.procs[0].poll() is not None
    api.post("/stream/stop")


def test_a_lost_camera_brings_a_fresh_picture(klipper, moonraker, monkeypatch):
    """ffmpeg says one of its cameras' inputs has ended (the camera hung up, or went quiet): a fresh picture, with new
    connections to every camera, takes over on the same connection to YouTube. What another input says doesn't count."""
    fake = FakeFfmpeg(lines=["[in#0/rtsp @ 0x5f] Terminating thread with return code -5 (I/O error)"])
    monkeypatch.setattr(live_stream.runner, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(live_stream.runner, "popen", fake)
    monkeypatch.setenv(live_stream.encoders.ENCODER_SETTING, "cpu")
    monkeypatch.setattr(live_stream.runner, "SETTLE", 0)
    monkeypatch.setattr(live_stream.runner, "REFRESH_EVERY", 0.2)
    api, pid = klipper
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False})
    api.post("/stream/start")
    assert _wait_for(lambda: len(fake.commands) >= 2)  # the first lost its camera: a fresh one took over
    assert _wait_for(lambda: fake.procs[0].poll() is not None) and len(fake.senders) == 1
    api.post("/stream/stop")

    quiet = FakeFfmpeg(lines=["[in#1/s16le @ 0x5f] Terminating thread with return code 0"])  # (the sound's input: not a camera)
    monkeypatch.setattr(live_stream.runner, "popen", quiet)
    api.post("/stream/start")
    assert _wait_for(lambda: quiet.commands)
    time.sleep(0.8)
    assert len(quiet.commands) == 1
    api.post("/stream/stop")


def test_a_layout_that_cant_start_beside_the_old_one_is_switched_to_directly(klipper, moonraker, ffmpeg, monkeypatch):
    """The new layout's picture can't start beside the one going out (a camera that takes one viewer at a time refuses
    it, and it ends): the one going out is stopped first, freeing the camera, and the new one started at once; the
    delay's buffer covers the gap. Still the same connection to YouTube."""
    real = ffmpeg.__call__
    started_with = []

    def picky(args, feed=False, out=False):
        proc = real(args, feed, out)
        if "-filter_complex" in args:
            started_with.append([p.poll() for p in ffmpeg.procs[:-1]])  # (were the earlier pictures still going?)
            if len(ffmpeg.commands) == 2:
                proc.terminate()  # the warming one: refused by the camera
        return proc

    monkeypatch.setattr(live_stream.runner, "popen", picky)
    api, pid = klipper
    moonraker.webcams = [_cam(), _cam(name="Nozzle")]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False})
    api.post("/stream/start")
    assert _wait_for(lambda: api.get("/stream").json()["status"]["on_air"])
    api.put("/stream", json={"cameras": [f"{pid}:Bed", f"{pid}:Nozzle"]})
    assert _wait_for(lambda: len(ffmpeg.commands) == 3)
    assert started_with[1] == [None] and started_with[2][0] is not None  # tried beside it first; then the old one stopped first
    assert _wait_for(lambda: api.get("/stream").json()["status"]["on_air"]) and len(ffmpeg.senders) == 1
    assert _wait_for(lambda: api.get("/stream").json()["status"]["error"] is None)
    api.post("/stream/stop")


def test_a_dropped_connection_is_made_again_and_its_message_clears(klipper, moonraker, ffmpeg, monkeypatch):
    """YouTube closes the connection: the sender is started again (after RETRY_SECONDS) and, once it has kept sending a
    while, the message saying it dropped is cleared. The picture keeps going throughout."""
    monkeypatch.setattr(live_stream.runner, "RETRY_SECONDS", 0.2)
    monkeypatch.setattr(live_stream.runner, "SENDER_STEADY", 0.3)
    api, pid = klipper
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False})
    api.post("/stream/start")
    assert _wait_for(lambda: ffmpeg.sender_procs and api.get("/stream").json()["status"]["on_air"])
    ffmpeg.sender_procs[0].terminate()  # YouTube hung up
    assert _wait_for(lambda: "connection to YouTube Live dropped" in (api.get("/stream").json()["status"]["error"] or ""))
    assert _wait_for(lambda: len(ffmpeg.senders) == 2)
    assert _wait_for(lambda: api.get("/stream").json()["status"]["error"] is None)
    assert len(ffmpeg.commands) == 1 and ffmpeg.procs[0].poll() is None
    api.post("/stream/stop")


def test_choosing_the_stream_folder(klipper, share):
    api, _ = klipper
    r = api.put("/stream/location", json={"path": str(share)})
    assert r.status_code == 200 and r.json()["is_default"] is False and r.json()["status"]["ready"] is True
    # looking at the page makes the stream folder's own folders, so each is there to copy into by hand
    assert not (share / "music").exists()
    assert api.get("/stream").json()["media"]["error"] is None
    assert all((share / name).is_dir() for name in ("images", "slideshows", "music"))
    api.post("/stream/pictures", files=[("files", ("a.png", _png(), "image/png"))])
    assert (share / "images" / "a.png").is_file()
    assert api.put("/stream/location", json={"path": None}).json()["is_default"] is True


def test_a_camera_that_only_plays_in_a_browser_is_refused(klipper, moonraker, ffmpeg):
    api, pid = klipper
    moonraker.webcams = [_cam(service="webrtc-janus", stream_url="/janus/")]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"]})
    r = api.post("/stream/start")
    assert r.status_code == 422 and "WebRTC" in r.json()["detail"]
    moonraker.webcams = [_cam(), _cam(name="Nozzle")]  # (one camera of several, gone: which it became can't be told)
    api.put("/stream", json={"cameras": [f"{pid}:Gone"]})
    assert "can't be reached" in api.post("/stream/start").json()["detail"]
    api.put("/stream", json={"cameras": ["999:Bed"]})
    assert "printer is gone" in api.post("/stream/start").json()["detail"]


def test_a_printers_only_camera_is_followed_when_renamed(klipper, moonraker, ffmpeg):
    api, pid = klipper
    # chosen as Bed, then switched to go2rtc in Mainsail, which named it Chamber
    moonraker.webcams = [_cam(name="Chamber", service="webrtc-go2rtc", stream_url="http://10.0.6.33:1984/stream.html?src=chamber&mode=webrtc")]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False})
    assert api.post("/stream/start").status_code == 200
    assert _wait_for(lambda: ffmpeg.commands)
    assert "rtsp://10.0.6.33:8554/chamber" in ffmpeg.commands[0]
    api.post("/stream/stop")


def test_a_renamed_camera_is_not_followed_onto_one_shown_already():
    from app.services.live_stream.sources import followed_camera

    only = [{"name": "Chamber"}]
    assert followed_camera("Bed", only, None) == only[0]
    assert followed_camera("Bed", only, None, {"Bed", "Chamber"}) is None  # another square shows it already
    assert followed_camera("Bed", only, "No answer") is None  # (the printer didn't answer in full)
    assert followed_camera("Bed", [*only, {"name": "Nozzle"}], None) is None


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
    from app.services.live_stream.sources import MJPEG, RTSP

    # (MJPEG: each frame timed as it arrives, and reconnected when the camera hangs up; RTSP: ends after 10 s quiet)
    assert "-reconnect" in MJPEG and "-use_wallclock_as_timestamps" in MJPEG and RTSP[-2:] == ["-timeout", "10000000"]
    assert live_stream.input_args(p, adaptive) == [*MJPEG, "-i", "http://10.0.6.21/webcam/?action=stream"]
    # go2rtc on the printer: the same camera over its RTSP port
    go2rtc = {"name": "Chamber", "service": "webrtc-go2rtc", "mjpeg": False, "stream_url": "http://10.0.6.33:1984/stream.html?src=chamber&mode=webrtc"}
    assert live_stream.input_args(p, go2rtc) == [*RTSP, "-i", "rtsp://10.0.6.33:8554/chamber"]


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


def test_a_stream_change_refreshes_only_the_settings_file():
    # the Stream page's setup file is written with the settings (test_config_service); no printer's or model's file
    from app import change_hooks

    scope = change_hooks._what_changed("/stream")
    assert scope is not None and scope.printers == set() and scope.models is False


# ------------------------------------------------------------------ YouTube: signing in, the title and description


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


def test_too_long_words_on_a_slideshow_picture(klipper):
    api, _ = klipper
    r = api.put("/stream", json={"cols": 1, "rows": 1, "cells": [{"slideshow": "Prints", "captions": {"b.png": {"text": "x" * 501}}}]})
    assert r.status_code == 422 and "b.png" in r.json()["detail"]


def test_a_slideshows_own_order(klipper, tmp_path):
    from app.services import stream_media

    api, _ = klipper
    api.post("/stream/slideshows", json={"name": "Sponsors"})
    files = [("files", (n, _png(n.encode()), "image/png")) for n in ("a.png", "b.png", "c.png")]
    api.post("/stream/slideshows/Sponsors/pictures", files=files)
    shows = api.put("/stream/slideshows/Sponsors/order", json={"order": ["c.png", "a.png"]}).json()["media"]["slideshows"]
    assert shows == [{"name": "Sponsors", "images": ["c.png", "a.png", "b.png"]}]  # one left out keeps its place after
    # kept in its folder: the stream and a scan follow it, and a picture added later goes on the end
    root = stream_media.folder(_db(api))
    assert [p.name for p in stream_media.slideshow_paths(_db(api), "Sponsors")] == ["c.png", "a.png", "b.png"]
    (root / "slideshows" / "Sponsors" / "0 new.png").write_bytes(_png())
    assert api.post("/stream/scan").json()["media"]["slideshows"][0]["images"] == ["c.png", "a.png", "b.png", "0 new.png"]
    r = api.put("/stream/slideshows/Sponsors/order", json={"order": ["nope.png"]})
    assert r.status_code == 422 and "nope.png" in r.json()["detail"]
    # deleting the slideshow takes its order file with it, so its folder goes too
    assert api.delete("/stream/slideshows/Sponsors?confirm=true").status_code == 200
    assert not (root / "slideshows" / "Sponsors").exists()


def test_renaming_a_slideshow(klipper, tmp_path):
    from app.services import stream_media

    api, _ = klipper
    api.post("/stream/slideshows", json={"name": "Given toys to"})
    api.post("/stream/slideshows", json={"name": "Sponsors"})
    api.post("/stream/slideshows/Given toys to/pictures", files=[("files", (n, _png(n.encode()), "image/png")) for n in ("a.png", "b.png")])
    api.put("/stream/slideshows/Given toys to/order", json={"order": ["b.png", "a.png"]})
    api.put("/stream", json={"cols": 2, "rows": 1, "cells": [{"slideshow": "Given toys to", "captions": {"a.png": {"text": "Hi"}}}, {"slideshow": "Sponsors"}]})
    layout = {"name": "Evening", "cols": 1, "rows": 1, "cells": [{"slideshow": "Given toys to"}]}
    api.put("/settings/config", json={"preferences": {"stream_layouts": [layout]}})

    # the folder on the server is renamed, its pictures and their order go with it
    page = api.put("/stream/slideshows/Given toys to", json={"name": "Schools 2026"}).json()
    assert [s["name"] for s in page["media"]["slideshows"]] == ["Schools 2026", "Sponsors"]
    assert page["media"]["slideshows"][0]["images"] == ["b.png", "a.png"]
    root = stream_media.folder(_db(api)) / "slideshows"
    assert sorted(p.name for p in root.iterdir()) == ["Schools 2026", "Sponsors"]
    # squares showing it follow, on the page and in saved layouts; the words on its pictures stay
    cells = page["settings"]["cells"]
    assert cells[0]["slideshow"] == "Schools 2026" and cells[0]["captions"] == {"a.png": {"text": "Hi", "text_box": cells[0]["captions"]["a.png"]["text_box"]}}
    assert cells[1]["slideshow"] == "Sponsors"
    saved = api.get("/settings/config").json()["config"]["preferences"]["stream_layouts"]
    assert saved[0]["cells"][0]["slideshow"] == "Schools 2026"

    # only its case changing is fine; a name another slideshow has, or one a folder can't have, isn't
    assert api.put("/stream/slideshows/Schools 2026", json={"name": "schools 2026"}).status_code == 200
    r = api.put("/stream/slideshows/schools 2026", json={"name": "SPONSORS"})
    assert r.status_code == 422 and "already a slideshow" in r.json()["detail"]
    assert api.put("/stream/slideshows/schools 2026", json={"name": "a/b"}).status_code == 422
    assert api.put("/stream/slideshows/Nope", json={"name": "Other"}).status_code == 404


def test_a_slideshows_blank_screens(klipper):
    from app.services import stream_media

    api, _ = klipper
    api.post("/stream/slideshows", json={"name": "Sponsors"})
    api.post("/stream/slideshows/Sponsors/pictures", files=[("files", ("a.png", _png(), "image/png"))])
    assert api.post("/stream/slideshows/Sponsors/blanks").status_code == 201
    shows = api.post("/stream/slideshows/Sponsors/blanks").json()["media"]["slideshows"]
    assert shows[0]["images"] == ["a.png", "blank:1", "blank:2"]
    # moved like a picture, and gone through to the stream as its name (no picture to read)
    api.put("/stream/slideshows/Sponsors/order", json={"order": ["blank:2", "a.png"]})
    paths = stream_media.slideshow_paths(_db(api), "Sponsors")
    assert [p if isinstance(p, str) else p.name for p in paths] == ["blank:2", "a.png", "blank:1"]
    # deleted as a picture is: out of the order
    shows = api.delete("/stream/slideshows/Sponsors/pictures/blank:1?confirm=true").json()["media"]["slideshows"]
    assert shows[0]["images"] == ["blank:2", "a.png"]


def test_the_page_is_told_how_long_the_picture_has_run(klipper, moonraker, ffmpeg):
    # the page shows the same slideshow picture and turn as the stream by counting from the same start
    api, pid = klipper
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"]})
    assert api.get("/stream").json()["status"]["running_for"] is None  # not live
    api.post("/stream/start")
    assert _wait_for(lambda: api.get("/stream").json()["status"]["on_air"])
    first = api.get("/stream").json()["status"]["running_for"]
    time.sleep(0.3)
    assert first is not None and api.get("/stream").json()["status"]["running_for"] > first
    api.post("/stream/stop")
    assert api.get("/stream").json()["status"]["running_for"] is None


def test_the_page_is_told_the_servers_time(klipper):
    api, _ = klipper
    before = time.time()
    assert before - 1 <= api.get("/stream").json()["status"]["server_time"] <= time.time() + 1


def test_the_resolution_is_set_when_going_live(klipper, moonraker, ffmpeg):
    # YouTube takes a change of size mid-stream badly: a new resolution saved while live waits for the next Go live,
    # and new layouts while live keep the size going out
    api, pid = klipper
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False, "resolution": "720p"})
    assert api.post("/stream/start").json()["status"]["resolution"] == "720p"
    page = api.put("/stream", json={"resolution": "1080p"}).json()
    assert page["settings"]["resolution"] == "1080p" and page["status"]["resolution"] == "720p" and len(ffmpeg.commands) == 1
    api.put("/stream", json={"border_color": "#FF0000"})  # a new layout: handed over to, at the size going out
    assert _wait_for(lambda: len(ffmpeg.commands) == 2)
    assert "scale=1280:720" in " ".join(ffmpeg.commands[-1]) and "scale=1920:1080" not in " ".join(ffmpeg.commands[-1])
    api.post("/stream/stop")
    assert api.get("/stream").json()["status"]["resolution"] is None
    assert api.post("/stream/start").json()["status"]["resolution"] == "1080p"
    assert "scale=1920:1080" in " ".join(ffmpeg.commands[-1])


def test_the_self_check_mends_a_stream_that_gives_youtube_nothing(klipper, moonraker, ffmpeg, monkeypatch):
    # left running day and night: when next to no video has come through for a while, the picture is started again,
    # and if that doesn't help, the connection to YouTube too; the page is told what was done
    api, pid = klipper
    monkeypatch.setattr(live_stream.runner, "CHECK_EVERY", 0.05)
    monkeypatch.setattr(live_stream.runner, "STALL", 0.4)
    monkeypatch.setattr(live_stream.runner, "RETRY_SECONDS", 0.05)
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False, "delay": 0})
    api.post("/stream/start")  # (the fake picture gives one keyframe and then nothing: no video comes through)
    assert _wait_for(lambda: len(ffmpeg.commands) >= 2)
    assert "picture was started again" in api.get("/stream").json()["status"]["self_check"]["message"]
    assert _wait_for(lambda: len(ffmpeg.senders) >= 2)  # that didn't help: the connection too
    assert "connection to YouTube" in api.get("/stream").json()["status"]["self_check"]["message"]
    api.post("/stream/stop")
    assert api.get("/stream").json()["status"]["self_check"] is None


def test_the_self_check_leaves_a_flowing_stream_alone(klipper, moonraker, ffmpeg, monkeypatch):
    api, pid = klipper
    monkeypatch.setattr(live_stream.runner, "CHECK_EVERY", 0.05)
    monkeypatch.setattr(live_stream.runner, "STALL", 0.4)
    monkeypatch.setattr(live_stream.relay.Relay, "last_time", lambda self: time.monotonic())  # video coming as it plays
    moonraker.webcams = [_cam()]
    api.put("/stream", json={"stream_key": KEY, "cameras": [f"{pid}:Bed"], "show_status": False, "delay": 0})
    api.post("/stream/start")
    time.sleep(1.2)
    assert len(ffmpeg.commands) == 1 and len(ffmpeg.senders) == 1
    assert api.get("/stream").json()["status"]["self_check"] is None
