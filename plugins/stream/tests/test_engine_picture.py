"""The engine copied from Farmhand (unchanged there): the picture ffmpeg is given (the grid and its squares, cards and slideshows, words, taking turns)."""
from __future__ import annotations

import os

import pytest

from streamer import live_stream


pytestmark = pytest.mark.usefixtures("stream_fresh")



def _graph(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_taking_turns_enlarges_only_the_camera_on_screen():
    srcs = [live_stream.Source(i, f"P{i}", ["-i", f"http://cam{i}"]) for i in range(3)]
    assert live_stream.windows(3, 30, 20) == (90, [(30, 50), (50, 70), (70, 90)])
    look = live_stream.Look(status_files=["/s/0.txt", "/s/1.txt", "/s/2.txt"], cycle=(30, 20), turns_file="/s/turns.txt")
    cmd = live_stream.command("ffmpeg", srcs, "rtmps://x/", look)
    graph = _graph(cmd)
    assert "split=2[g0][s0]" in graph and "xstack=inputs=4" in graph  # 3 cameras in a 2x2 grid, one square empty
    # every camera's picture goes to the switch with its words on, and only what comes through is made full size
    assert "[s1]drawtext=" in graph and "fontsize=h/26" in graph
    assert "[w0][w1][w2]streamselect@pick=inputs=3:map=0,scale=1280:720" in graph
    assert graph.count("scale=1280:720") == 2  # the grid once, the camera on screen once: never one per camera
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
    assert square["[g1]"].startswith("[g1]scale=420:354:force_original_aspect_ratio=decrease,pad=426:360") and square["[g1]"].endswith("[c1]")  # camera 1 in the second square
    assert square["[g0]"].endswith("[c5]")  # camera 0 in the last
    # 1x1: the one square is the whole picture
    one = _graph(live_stream.command("ffmpeg", srcs[:1], "u", live_stream.Look(cols=1, rows=1, cells=[("camera", 0)])))
    assert "xstack" not in one and "[c0]scale=1280:720" in one


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
    assert "[g0]scale=634:714:force_original_aspect_ratio=decrease,pad=640:720:(ow-iw)/2:(oh-ih)/2:color=0x00FF00" in graph
    assert "[g1]scale=634:714:force_original_aspect_ratio=decrease,pad=640:720:(ow-iw)/2:(oh-ih)/2:color=0x112233" in graph


def test_a_slideshow_is_put_together_once(tmp_path):
    """Each screen of a slideshow as one finished picture (its colour, its picture fitted in its box, the screen's more
    pictures), and the list ffmpeg reads them from, starting on the screen the time of day says."""
    from PIL import Image

    from streamer.live_stream import slides
    from streamer.live_stream.frame import Frame

    for name, colour, size in (("wide.png", (255, 0, 0), (200, 100)), ("logo.png", (0, 0, 255), (50, 50))):
        Image.new("RGB", size, colour).save(tmp_path / name)
    frame = Frame.of("720p", 2, 2, "#000000", "#000000")  # squares 640 x 360, a 3 px border
    cd = {"background": "#00FF00", "picture_box": {"x": 0, "y": 0, "w": 1, "h": 1},
          "picture_boxes": {"wide.png": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}}}
    frames = slides.compose(cd, [str(tmp_path / "wide.png"), "blank:1"], {1: [{"path": str(tmp_path / "logo.png"), "box": {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}}]},
                            frame, str(tmp_path / "out"))
    one, two = (Image.open(f).convert("RGB") for f in frames)
    assert one.size == two.size == (640, 360)
    # the picture in its own box (the top-left quarter inside the border), keeping its shape: 317 x 158 of red, centred
    assert one.getpixel((20, 50)) == (255, 0, 0) and one.getpixel((20, 8)) == (0, 255, 0) and one.getpixel((600, 300)) == (0, 255, 0)
    # the blank screen: its colour, and its own more picture in the bottom-right quarter (kept square, centred)
    assert two.getpixel((10, 10)) == (0, 255, 0) and two.getpixel((480, 270)) == (0, 0, 255)

    # the list: each screen for its seconds, starting 7 s into a 10 s round of two 5 s screens (on the second, 3 s left)
    listed = open(slides.playlist(frames, 5, 1_000_007, str(tmp_path / "list.txt"), horizon=30), encoding="utf-8").read().splitlines()
    assert listed[0] == "ffconcat version 1.0"
    assert listed[1:7] == [f"file '{frames[1]}'", "duration 3", f"file '{frames[0]}'", "duration 5", f"file '{frames[1]}'", "duration 5"]
    assert sum(float(l.split()[1]) for l in listed if l.startswith("duration")) >= 30


def test_the_grid_and_the_words():
    assert live_stream.grid(1, 1280, 720) == (1, 1, 1280, 720)
    assert live_stream.grid(3, 1280, 720) == (2, 2, 640, 360)
    assert live_stream.grid(5, 1280, 720) == (3, 2, 426, 360)
    assert live_stream.grid(4) == (2, 2, 640, 360)  # 720p unless chosen otherwise
    assert live_stream.auto_grid(0) == (1, 1) and live_stream.auto_grid(7) == (3, 3) and live_stream.auto_grid(25) == (5, 5)
    assert live_stream.status_line("VT 1190", {"state": "printing", "progress": 41.6, "file": "jobs/benchy.gcode"}) == "VT 1190 · Printing 42% · benchy.gcode"
    assert live_stream.status_line("VT 1190", {"state": "paused", "progress": None, "file": None}) == "VT 1190 · Paused"
    assert live_stream.status_line("VT 1190", {"state": None}) == "VT 1190 · Idle"
    assert live_stream.status_line("Prusa_2", {"state": None, "error": "PrusaLink refused the login."}) == "Prusa_2 · Status unknown"


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


def test_play_is_kept_with_the_plugin():
    assert live_stream.font_file("play").replace("\\", "/").endswith("streamer/fonts/Play-Regular.ttf")
    assert os.path.isfile(live_stream.font_file("play-bold"))


def test_a_slideshow_pictures_own_words():
    cell = live_stream._cell({"slideshow": "Prints", "text": "Every one", "captions": {
        "b.png": {"text": "Benchy", "text_box": {"x": 0.2, "y": 0.8, "size": 0.1}}, "c.png": {"text": "  "}, "../x": {"text": "no"}}})
    assert cell["captions"] == {"b.png": {"text": "Benchy", "text_box": {"x": 0.2, "y": 0.8, "size": 0.1}}}  # words only, good names only
    assert live_stream._cell({"image": "a.png", "captions": {"a.png": {"text": "x"}}})["captions"] == {}  # a slideshow's only
    # b's own words only while b shows (5 to 10 s of every 15); the card's words while a and c show
    cells = [("card", {"pictures": ["/s/a.png", "/s/b.png", "/s/c.png"], "seconds": 5, "words": "/s/t.txt",
                       "picture_words": {1: {"words": "/s/t-1.txt", "text_box": {"x": 0.2, "y": 0.8, "size": 0.1}}}})]
    graph = _graph(live_stream.command("ffmpeg", [], "u", live_stream.Look(cols=1, rows=1, cells=cells, resolution="720p")))
    card_words = graph.split("textfile=/s/t.txt")[1].split("[c0]")[0].split(",drawtext")[0]
    assert "enable='gte(mod(t,15),0)*lt(mod(t,15),5)+gte(mod(t,15),10)*lt(mod(t,15),15)'" in card_words
    own = graph.split("textfile=/s/t-1.txt")[1]
    assert "x=256-text_w/2:y=576-text_h/2" in own and "enable='gte(mod(t,15),5)*lt(mod(t,15),10)'" in own


def test_a_blank_screen_in_the_picture():
    # a picture, then a blank screen with words of its own: the picture only in its turn, the words only in theirs
    cells = [("card", {"pictures": ["/s/a.png", "blank:1"], "seconds": 5,
                       "picture_words": {1: {"words": "/s/t-1.txt", "text_box": {"x": 0.5, "y": 0.5, "size": 0.2}}}})]
    cmd = live_stream.command("ffmpeg", [], "u", live_stream.Look(cols=1, rows=1, cells=cells, resolution="720p"))
    graph = _graph(cmd)
    assert [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"][1:] == ["/s/a.png"]  # nothing read for the blank screen
    assert "overlay=(W-w)/2:(H-h)/2:enable='gte(mod(t,10),0)*lt(mod(t,10),5)'" in graph
    assert "textfile=/s/t-1.txt" in graph and "enable='gte(mod(t,10),5)*lt(mod(t,10),10)'" in graph.split("textfile=/s/t-1.txt")[1]


def test_the_stream_is_compressed_by_an_nvidia_card_when_one_works(monkeypatch):
    from streamer.live_stream import encoders as runner

    monkeypatch.delenv(runner.ENCODER_SETTING, raising=False)
    runner._found_encoder.clear()
    monkeypatch.setattr(runner, "_nvenc_works", lambda ffmpeg: True)
    assert runner.encoder("ffmpeg") == "nvenc"
    runner._found_encoder.clear()
    monkeypatch.setattr(runner, "_nvenc_works", lambda ffmpeg: False)  # no card, no driver, or an ffmpeg without it
    assert runner.encoder("ffmpeg") == "cpu"
    monkeypatch.setenv(runner.ENCODER_SETTING, "nvenc")  # said outright: not tried
    assert runner.encoder("ffmpeg") == "nvenc"
    runner._found_encoder.clear()
    cmd = live_stream.command("ffmpeg", [], "u", live_stream.Look(cols=1, rows=1, cells=[None], resolution="720p", encoder="nvenc"))
    assert cmd[cmd.index("-c:v") + 1] == "h264_nvenc" and "libx264" not in cmd and cmd[cmd.index("-b:v") + 1] == "2500k"
    cmd = live_stream.command("ffmpeg", [], "u", live_stream.Look(cols=1, rows=1, cells=[None], resolution="720p"))
    assert cmd[cmd.index("-c:v") + 1] == "libx264"  # the processor, unless said


def test_slideshows_and_turns_keep_the_time_of_day():
    # going live at 125 s past a round's start: a 3 x 5 s slideshow is 5 s into b (125 mod 15 = 5); the turns of two
    # cameras (10 s all, then 5 s each: a 20 s round) are 5 s into the whole grid's 10 s
    cells = [("camera", 0), ("camera", 1), ("card", {"pictures": ["/s/a.png", "/s/b.png", "/s/c.png"], "seconds": 5})]
    srcs = [live_stream.Source(i, f"P{i}", ["-i", f"http://cam{i}"]) for i in range(2)]
    graph = _graph(live_stream.command("ffmpeg", srcs, "u", live_stream.Look(cols=3, rows=1, cells=cells, resolution="720p", clock=1_700_000_125)))
    off = 1_700_000_125 % 15
    assert f"enable='gte(mod(t+{off},15),5)*lt(mod(t+{off},15),10)'" in graph
    t = live_stream.timetable(2, 10, 5, horizon=60, clock=1_700_000_125).splitlines()
    phase = 1_700_000_125 % 20  # 5: in the whole grid's turn, which shows at once; camera 0 at 5 s, camera 1 at 10 s
    assert phase == 5 and t[0] == "0 streamselect@view map 0;"
    assert t[1:4] == ["5 streamselect@view map 1, streamselect@pick map 0;", "10 streamselect@view map 1, streamselect@pick map 1;",
                      "15 streamselect@view map 0;"]
    # partway through a camera's turn, that camera at once
    assert live_stream.timetable(2, 10, 5, horizon=60, clock=12).splitlines()[0] == "0 streamselect@view map 1, streamselect@pick map 0;"
    # counted from the start of a round, as before
    assert live_stream.timetable(2, 10, 5, horizon=40, clock=0).splitlines() == [
        "0 streamselect@view map 0;", "10 streamselect@view map 1, streamselect@pick map 0;", "15 streamselect@view map 1, streamselect@pick map 1;",
        "20 streamselect@view map 0;", "30 streamselect@view map 1, streamselect@pick map 0;", "35 streamselect@view map 1, streamselect@pick map 1;"]


def test_a_slideshow_picture_resized_on_its_own():
    cell = live_stream._cell({"slideshow": "Prints", "picture_boxes": {"b.png": {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}, "../x": {"w": 1}}})
    assert cell["picture_boxes"] == {"b.png": {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}}
    assert live_stream._cell({"image": "a.png", "picture_boxes": {"a.png": {"w": 0.5}}})["picture_boxes"] == {}  # a slideshow's only
    # b in its own box (the lower right quarter, inside the border); a and c as the card's (the whole square)
    cells = [("card", {"pictures": ["/s/a.png", "/s/b.png", "/s/c.png"], "seconds": 5,
                       "picture_boxes": {"b.png": {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}}})]
    graph = _graph(live_stream.command("ffmpeg", [], "u", live_stream.Look(cols=1, rows=1, cells=cells, resolution="720p")))
    assert "[1:v]scale=1274:714:" in graph and "[3:v]scale=1274:714:" in graph
    assert "[2:v]scale=637:357:" in graph and "overlay=640+(637-w)/2:360+(357-h)/2:enable=" in graph


def test_a_slideshow_screens_words_are_drawn_on_that_screen_only(tmp_path):
    """Each screen's caption is part of the screen's own picture, so it can only ever show with its own picture (with
    drawtext in its seconds, the live stream's slideshow and words drifted apart: one sponsor's name on another's logo)."""
    from PIL import Image

    from streamer.live_stream import slides
    from streamer.live_stream.fonts import font_file
    from streamer.live_stream.frame import Frame

    for name in ("a.png", "b.png"):
        Image.new("RGB", (40, 40), (255, 255, 255)).save(tmp_path / name)
    frame = Frame.of("720p", 2, 2, "#000000", "#000000")
    cd = {"background": "#00FF00", "picture_box": {"x": 0, "y": 0, "w": 0.2, "h": 0.2}}
    words = {1: [{"text": "Bearded\nPrinter", "tb": {"x": 0.5, "y": 0.6, "size": 0.2}, "font": font_file(None), "color": "#FF0000", "band": True}]}
    a, b = slides.compose(cd, [str(tmp_path / "a.png"), str(tmp_path / "b.png")], {}, frame, str(tmp_path / "out"),
                          cache=str(tmp_path / "cache"), screen_words=words)
    red = lambda im: sum(1 for px in im.getdata() if px[0] > 200 and px[1] < 60 and px[2] < 60)  # noqa: E731
    one, two = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    assert red(one) == 0 and red(two) > 200  # the words on the second screen only
    assert two.getpixel((320, 216))[1] < 255  # the band darkens the green round them
    # the same screen without words is another picture (the words are part of what it's kept by)
    plain = slides.compose(cd, [str(tmp_path / "b.png")], {}, frame, str(tmp_path / "out2"), cache=str(tmp_path / "cache"))
    assert plain[0] != b


def test_each_line_of_a_screens_words_is_centred_as_the_page_shows_it():
    """Words of more than one line: each line centred on the spot (not lined up on the left, as Pillow and drawtext do
    unless told), so a short line over a long one sits in the middle, as on the page."""
    from PIL import Image

    from streamer.live_stream import fonts, slides
    from streamer.live_stream.frame import Frame

    frame = Frame.of("720p", 1, 1, "#FFFFFF", "#000000")
    canvas = Image.new("RGBA", (frame.tw, frame.th), (255, 255, 255, 255))
    words = {"text": "Hi\nhttps://www.3dprintingelves.org", "tb": {"x": 0.5, "y": 0.5, "size": 0.1},
             "font": fonts.font_file(None), "color": "#FF0000", "band": False}
    slides._draw_words(canvas, words, frame)
    red = [(x, y) for y in range(frame.th) for x in range(0, frame.tw, 2)
           if canvas.getpixel((x, y))[0] > 200 and canvas.getpixel((x, y))[1] < 80]
    top = min(y for _, y in red)
    first = [x for x, y in red if y < top + 0.05 * frame.th]  # the short first line
    middle = (min(first) + max(first)) / 2
    assert abs(middle - frame.tw / 2) < 0.02 * frame.tw  # centred, not over on the left
