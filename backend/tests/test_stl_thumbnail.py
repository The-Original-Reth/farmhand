from __future__ import annotations

import io

import numpy as np
from PIL import Image

from app.thumbnails import stl_render
from app.thumbnails.stl_render import render_stl_thumbnail

TETRA = np.array([[(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 0), (1, 0, 0), (0, 0, 1)],
                  [(0, 0, 0), (0, 1, 0), (0, 0, 1)], [(1, 0, 0), (0, 1, 0), (0, 0, 1)]], dtype=np.float32)


def _write_binary(path, tris, header=b"binary stl"):
    rec = np.zeros(len(tris), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["v"] = tris
    path.write_bytes(header.ljust(80, b" ") + np.uint32(len(tris)).tobytes() + rec.tobytes())
    return path


def _write_ascii(path, tris):
    lines = ["solid test"]
    for t in tris:
        lines += ["facet normal 0 0 0", "outer loop"] + [f"vertex {x} {y} {z}" for x, y, z in t] + ["endloop", "endfacet"]
    path.write_text("\n".join(lines + ["endsolid test"]))
    return path


def _sphere(n_lat, n_lon):
    """A closed UV sphere with 2 * n_lat * n_lon triangles."""
    la, lo = np.meshgrid(np.linspace(0, np.pi, n_lat + 1), np.linspace(0, 2 * np.pi, n_lon + 1), indexing="ij")
    p = np.stack([np.sin(la) * np.cos(lo), np.sin(la) * np.sin(lo), np.cos(la)], -1).astype(np.float32)
    a, b, c, d = p[:-1, :-1], p[1:, :-1], p[1:, 1:], p[:-1, 1:]
    return np.concatenate([np.stack([a, b, c], 2).reshape(-1, 3, 3), np.stack([a, c, d], 2).reshape(-1, 3, 3)])


def _cube():
    v = np.array([(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)], dtype=np.float32)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return np.array([[v[q[0]], v[q[1]], v[q[2]]] for q in quads] + [[v[q[0]], v[q[2]], v[q[3]]] for q in quads])


def _image(png, size=256):
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))


def _white_pixels_in_centre_disc(pixels, fraction):
    """Count pure-white pixels inside a disc around the tile's centre — holes in a model that should be solid."""
    h, w, _ = pixels.shape
    yy, xx = np.mgrid[0:h, 0:w]
    disc = (xx - w / 2) ** 2 + (yy - h / 2) ** 2 <= (fraction * min(h, w) / 2) ** 2
    return int((pixels[disc] == 255).all(axis=1).sum())


def test_thumbnail_has_an_opaque_white_background(tmp_path):
    im = Image.open(io.BytesIO(render_stl_thumbnail(str(_write_binary(tmp_path / "t.stl", TETRA))))).convert("RGBA")
    for corner in [(0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1)]:
        assert im.getpixel(corner) == (255, 255, 255, 255)  # white and fully opaque, not transparent
    assert any(im.getpixel((x, y))[:3] != (255, 255, 255) for x in range(im.width) for y in range(im.height))  # the model is drawn


def test_a_detailed_model_is_drawn_solid_not_see_through(tmp_path):
    """
    Regression: models over ~150k triangles used to have most of their triangles thrown away to save time,
    leaving the surface perforated — a see-through, wireframe-looking preview.
    """
    tris = _sphere(400, 400)  # 320,000 triangles: well over the old cutoff
    assert len(tris) > 300_000
    png = render_stl_thumbnail(str(_write_binary(tmp_path / "dense.stl", tris)), size_px=128)
    assert _white_pixels_in_centre_disc(_image(png), 0.80) == 0  # no holes anywhere inside the ball


def test_every_triangle_is_used(tmp_path, monkeypatch):
    seen = []
    real = stl_render._render
    monkeypatch.setattr(stl_render, "_render", lambda verts, size: (seen.append(len(verts)), real(verts, size))[1])
    tris = _sphere(300, 300)  # 180,000
    render_stl_thumbnail(str(_write_binary(tmp_path / "dense.stl", tris)), size_px=64)
    assert seen == [len(tris)]  # nothing thinned out


def test_a_simple_model_made_of_a_few_big_faces_is_solid_too(tmp_path):
    png = render_stl_thumbnail(str(_write_binary(tmp_path / "cube.stl", _cube())), size_px=128)
    assert _white_pixels_in_centre_disc(_image(png), 0.60) == 0


def test_inconsistent_triangle_winding_does_not_leave_holes_or_dark_faces(tmp_path):
    tris = _sphere(120, 120).copy()
    flip = np.random.default_rng(1).random(len(tris)) < 0.5
    tris[flip] = tris[flip][:, ::-1]  # half the triangles wound the other way: common in real-world meshes
    pixels = _image(render_stl_thumbnail(str(_write_binary(tmp_path / "flipped.stl", tris)), size_px=128))
    assert _white_pixels_in_centre_disc(pixels, 0.80) == 0
    centre = pixels[40:88, 40:88].reshape(-1, 3).astype(int)
    assert centre.min() > 30  # no faces rendered black because they faced "backwards"


def test_the_model_fills_most_of_the_tile(tmp_path):
    pixels = _image(render_stl_thumbnail(str(_write_binary(tmp_path / "s.stl", _sphere(60, 60))), size_px=128))
    rows, cols = np.where((pixels != 255).any(axis=2))
    assert max(rows.max() - rows.min(), cols.max() - cols.min()) >= 0.80 * 128  # not a speck in a sea of white


def test_ascii_stl_files_get_a_preview_too(tmp_path):
    png = render_stl_thumbnail(str(_write_ascii(tmp_path / "ascii.stl", _cube())), size_px=96)
    assert png is not None and _white_pixels_in_centre_disc(_image(png), 0.60) == 0


def test_a_binary_stl_whose_header_says_solid_is_still_read_as_binary(tmp_path):
    png = render_stl_thumbnail(str(_write_binary(tmp_path / "x.stl", _cube(), header=b"solid exported by something")), size_px=96)
    assert png is not None and _white_pixels_in_centre_disc(_image(png), 0.60) == 0


def test_unreadable_files_give_no_preview_instead_of_an_error(tmp_path):
    (tmp_path / "empty.stl").write_bytes(b"")
    (tmp_path / "junk.stl").write_bytes(b"\x00\x01\x02 not a model " * 50)
    truncated = _write_binary(tmp_path / "cut.stl", _cube())
    truncated.write_bytes(truncated.read_bytes()[:200])  # says 12 triangles, holds fewer
    for name in ("empty.stl", "junk.stl", "cut.stl", "missing.stl"):
        assert render_stl_thumbnail(str(tmp_path / name)) is None


def test_bad_triangles_are_ignored_not_fatal(tmp_path):
    bad = np.concatenate([TETRA, np.full((1, 3, 3), np.nan, dtype=np.float32), np.zeros((1, 3, 3), dtype=np.float32)])
    png = render_stl_thumbnail(str(_write_binary(tmp_path / "bad.stl", bad)), size_px=64)
    assert png is not None  # the NaN triangle and the zero-area one are skipped; the real ones draw
