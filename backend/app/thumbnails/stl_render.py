"""
Auto-framed, solid-shaded thumbnails for STL files.

Per spec section 6 the eventual pipeline is occt-import-js + three.js, shared across
STL/OBJ/STEP, with STEP explicitly deferred. This is a genuine interim implementation for STL
(binary and ASCII) — camera fit to the bounding box, one default viewing angle — so the library
isn't showing blank thumbnails in the meantime. OBJ and STEP aren't rendered; they return None.

How it draws: a small software rasterizer with a depth buffer, in numpy. EVERY triangle is drawn
(an earlier version thinned big models to keep matplotlib fast, which left the surface
perforated — a see-through "wireframe" look on anything over ~150k triangles). A depth buffer also
gives correct hidden surfaces without sorting tricks and no seams between neighbouring triangles.
Edges are anti-aliased by drawing at 2-3x resolution and averaging down.

Triangles are handled in two groups:
  * small ones (the vast majority on a detailed model) are tested against every pixel centre they
    could cover, all triangles at once, one pixel offset at a time (vectorised)
  * big ones (a few flat faces on a simple model) get an ordinary per-triangle fill
"""
from __future__ import annotations

import io
import re
import struct

import numpy as np

FILL = 0.88  # how much of the tile the model's silhouette takes up
SMALL_EXTENT = 6  # triangles covering at most this many pixel centres per axis take the vectorised path
BASE_COLOR = np.array([0.30, 0.58, 0.62], dtype=np.float32)  # the archive's teal accent
KEY_LIGHT = np.array([0.40, 0.50, 0.90], dtype=np.float32)
FILL_LIGHT = np.array([-0.70, -0.20, 0.50], dtype=np.float32)
_ASCII_VERTEX = re.compile(rb"vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)")


def render_stl_thumbnail(stl_path: str, size_px: int = 256) -> bytes | None:
    try:
        verts = _read_stl(stl_path)
    except Exception:
        return None  # unreadable: a missing preview is better than a blocked upload
    verts = verts[np.isfinite(verts).all(axis=(1, 2))]
    if len(verts) == 0:
        return None
    try:
        return _png(_render(verts, size_px))
    except Exception:
        return None


# ------------------------------------------------------------------ reading


def _read_stl(path: str) -> np.ndarray:
    """All triangles as float32 (n, 3, 3). Binary STL, or ASCII STL when the size doesn't fit binary."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if len(data) == 84 + 50 * n:  # exact fit — binary (even if its header happens to start with "solid")
            arr = np.frombuffer(data, dtype=np.uint8, count=n * 50, offset=84).reshape(n, 50)
            return np.frombuffer(arr[:, 12:48].tobytes(), dtype="<f4").reshape(n, 3, 3).astype(np.float32)
    found = _ASCII_VERTEX.findall(data)
    if not found:
        raise ValueError("Not a readable STL file")
    flat = np.array(found, dtype=np.float32)
    return flat[: len(flat) // 3 * 3].reshape(-1, 3, 3)


# ------------------------------------------------------------------ drawing


def _render(verts: np.ndarray, size_px: int) -> np.ndarray:
    ss = 2  # 2x2 samples per pixel: smooth edges at the size previews are shown, at a quarter of the 4x4 cost
    size = size_px * ss

    # frame to the model's own bounding box, then a fixed 3/4 view
    flat = verts.reshape(-1, 3)
    lo, hi = flat.min(axis=0), flat.max(axis=0)
    v = (verts - (lo + hi) / 2) / (float((hi - lo).max()) or 1.0)
    elev, azim = np.radians(28.0), np.radians(-52.0)
    rz = np.array([[np.cos(azim), -np.sin(azim), 0], [np.sin(azim), np.cos(azim), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(elev), -np.sin(elev)], [0, np.sin(elev), np.cos(elev)]])
    v = (v @ (rx @ rz).T.astype(np.float32)).astype(np.float32)  # x right, y up, z toward the viewer

    # shading from the real geometry (an STL's stored normals are often missing or wrong)
    normal = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    normal /= np.linalg.norm(normal, axis=1, keepdims=True) + 1e-12
    normal *= np.where(normal[:, 2:3] < 0, -1.0, 1.0).astype(np.float32)  # face the viewer whatever the winding
    key = np.clip(normal @ (KEY_LIGHT / np.linalg.norm(KEY_LIGHT)), 0, 1)
    fill = np.clip(normal @ (FILL_LIGHT / np.linalg.norm(FILL_LIGHT)), 0, 1)
    shade = np.clip(0.22 + 0.70 * key + 0.18 * fill, 0, 1).astype(np.float32)

    # fit the picture to the silhouette actually on screen, so the model fills most of the tile
    # (small previews are far easier to read that way)
    px, py = v[:, :, 0], v[:, :, 1]
    cx_, cy_ = (px.min() + px.max()) / 2, (py.min() + py.max()) / 2
    span = max(float(px.max() - px.min()), float(py.max() - py.min())) / FILL or 1.0
    sx = (((px - cx_) / span + 0.5) * size).astype(np.float64)
    sy = ((0.5 - (py - cy_) / span) * size).astype(np.float64)
    sz = v[:, :, 2].astype(np.float64)

    depth = np.full(size * size, -np.inf, dtype=np.float32)
    level = np.full(size * size, -1.0, dtype=np.float32)  # shade of the nearest triangle; -1 = nothing drawn
    _rasterize(sx, sy, sz, shade, size, depth, level)

    img = np.ones((size * size, 3), dtype=np.float32)  # white background
    drawn = level >= 0
    img[drawn] = BASE_COLOR[None, :] * level[drawn][:, None]
    img = img.reshape(size_px, ss, size_px, ss, 3).mean(axis=(1, 3))  # average down: anti-aliased edges
    return (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)


def _rasterize(sx, sy, sz, shade, size, depth, level) -> None:
    # Pixel centres a triangle's bounding box can contain: ix0 .. ix0+cx-1 (cx <= 0 means none: the
    # triangle falls between pixel centres, and its neighbours cover them)
    ix0 = np.ceil(sx.min(axis=1) - 0.5).astype(np.int64)
    iy0 = np.ceil(sy.min(axis=1) - 0.5).astype(np.int64)
    cx = np.floor(sx.max(axis=1) - 0.5).astype(np.int64) - ix0 + 1
    cy = np.floor(sy.max(axis=1) - 0.5).astype(np.int64) - iy0 + 1

    x0, x1, x2 = sx[:, 0], sx[:, 1], sx[:, 2]
    y0, y1, y2 = sy[:, 0], sy[:, 1], sy[:, 2]
    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    usable = (cx > 0) & (cy > 0) & (np.abs(area) > 1e-12)

    small = np.flatnonzero(usable & (cx <= SMALL_EXTENT) & (cy <= SMALL_EXTENT))
    large = np.flatnonzero(usable & ((cx > SMALL_EXTENT) | (cy > SMALL_EXTENT)))

    # ---- small triangles: all at once, one pixel offset at a time
    for start in range(0, len(small), 200_000):  # chunked to bound memory on very large meshes
        idx = small[start : start + 200_000]
        for dx in range(SMALL_EXTENT):
            for dy in range(SMALL_EXTENT):
                sel = np.flatnonzero((cx[idx] > dx) & (cy[idx] > dy))
                if len(sel) == 0:
                    continue
                t = idx[sel]
                px = ix0[t] + dx
                py = iy0[t] + dy
                fx, fy = px + 0.5, py + 0.5
                w0 = ((x1[t] - fx) * (y2[t] - fy) - (x2[t] - fx) * (y1[t] - fy)) / area[t]
                w1 = ((x2[t] - fx) * (y0[t] - fy) - (x0[t] - fx) * (y2[t] - fy)) / area[t]
                w2 = 1.0 - w0 - w1
                ok = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9) & (px >= 0) & (px < size) & (py >= 0) & (py < size)
                if not ok.any():
                    continue
                t, px, py, w0, w1, w2 = t[ok], px[ok], py[ok], w0[ok], w1[ok], w2[ok]
                z = w0 * sz[t, 0] + w1 * sz[t, 1] + w2 * sz[t, 2]
                _merge(depth, level, py * size + px, z, shade[t])

    # ---- large triangles: an ordinary fill, one at a time (there are few of these)
    for t in large:
        xs = np.arange(max(ix0[t], 0), min(ix0[t] + cx[t], size))
        ys = np.arange(max(iy0[t], 0), min(iy0[t] + cy[t], size))
        if len(xs) == 0 or len(ys) == 0:
            continue
        fx = xs + 0.5  # (nx,) and (ny, 1): broadcasting, which is much cheaper than building meshgrids per triangle
        fy = (ys + 0.5)[:, None]
        w0 = ((x1[t] - fx) * (y2[t] - fy) - (x2[t] - fx) * (y1[t] - fy)) / area[t]
        w1 = ((x2[t] - fx) * (y0[t] - fy) - (x0[t] - fx) * (y2[t] - fy)) / area[t]
        w2 = 1.0 - w0 - w1
        ok = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not ok.any():
            continue
        z = (w0 * sz[t, 0] + w1 * sz[t, 1] + w2 * sz[t, 2])[ok]
        rows, cols = np.nonzero(ok)
        lin = (ys[rows]).astype(np.int64) * size + xs[cols]
        _merge(depth, level, lin, z, np.full(len(z), shade[t], dtype=np.float32))


def _merge(depth, level, lin, z, shade) -> None:
    """Depth-test fragments into the buffers: for each pixel the nearest fragment wins."""
    order = np.lexsort((z, lin))  # by pixel, then by depth ascending
    lin, z, shade = lin[order], z[order], shade[order]
    last = np.ones(len(lin), dtype=bool)
    last[:-1] = lin[1:] != lin[:-1]  # the nearest fragment for each pixel in this batch
    lin, z, shade = lin[last], z[last], shade[last]
    nearer = z > depth[lin]
    depth[lin[nearer]] = z[nearer]
    level[lin[nearer]] = shade[nearer]


def _png(rgb: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
