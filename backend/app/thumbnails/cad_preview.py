"""
Previews for a project's CAD files, drawn like an STL's wherever the file can be turned into triangles:

  * STL: as an STL
  * OBJ: its faces, read here
  * STEP / IGES / BREP: turned into triangles by gmsh (OpenCascade), in a separate process (cad_mesh.py) so a file it
    can't handle, or one that takes too long, never holds up or brings down the API
  * Fusion (.f3d, .f3z) and anything else that is a ZIP with a picture inside (a 3MF's thumbnail): that picture

Anything else (a SolidWorks or Inventor file, an OpenSCAD script...) has no preview. Every path fails soft: no preview
is better than a blocked upload.
"""
from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from .stl_render import render_stl_thumbnail, render_triangles

log = logging.getLogger("farmhand.cad_preview")

MESHED = {".step", ".stp", ".iges", ".igs", ".brep", ".brp"}  # what gmsh can turn into triangles
MESH_TIMEOUT_S = 90  # a huge assembly can take a while; past this it goes without a preview
SIZE_PX = 256
_PICTURE = (".png", ".jpg", ".jpeg")


def render_cad_preview(path: str, size_px: int = SIZE_PX) -> bytes | None:
    """A PNG preview of the CAD file at `path`, or None when one can't be made."""
    ext = Path(path).suffix.lower()
    try:
        if ext == ".stl":
            return render_stl_thumbnail(path, size_px)
        if ext == ".obj":
            return render_triangles(_read_obj(path), size_px)
        if ext in MESHED:
            verts = _mesh(path)
            return render_triangles(verts, size_px) if verts is not None else None
        if zipfile.is_zipfile(path):
            return _picture_inside(path, size_px)
    except Exception as e:  # noqa: BLE001 - any file, any failure: no preview
        log.info("No preview for %s: %s", path, e)
    return None


# ------------------------------------------------------------------ OBJ


def _read_obj(path: str) -> np.ndarray:
    """Every face as triangles (a polygon is fanned from its first corner), (n, 3, 3)."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("v "):
                x, y, z = line.split()[1:4]
                vertices.append((float(x), float(y), float(z)))
            elif line.startswith("f "):
                # "f 1 2 3", "f 1/1 2/2 3/3", "f 1//1 ..."; negative = counted from the end
                corners = [int(p.split("/")[0]) for p in line.split()[1:]]
                faces.append([c - 1 if c > 0 else len(vertices) + c for c in corners])
    v = np.asarray(vertices, dtype=np.float32)
    tris = [(face[0], face[i], face[i + 1]) for face in faces for i in range(1, len(face) - 1)]
    if not tris or not len(v):
        return np.zeros((0, 3, 3), dtype=np.float32)
    return v[np.asarray(tris)]


# ------------------------------------------------------------------ STEP and friends


def _mesh(path: str) -> np.ndarray | None:
    """The file's surfaces as triangles, from cad_mesh.py run as its own process. None when it couldn't."""
    with tempfile.TemporaryDirectory(prefix="farmhand-cad-") as tmp:
        out = os.path.join(tmp, "triangles.npy")
        try:
            done = subprocess.run(
                [sys.executable, "-m", "app.thumbnails.cad_mesh", path, out],
                cwd=str(Path(__file__).resolve().parents[2]),  # the folder app/ is in
                capture_output=True,
                timeout=MESH_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            log.info("Gave up turning %s into triangles after %ss", path, MESH_TIMEOUT_S)
            return None
        if done.returncode != 0 or not os.path.isfile(out):
            log.info("Couldn't turn %s into triangles: %s", path, done.stderr.decode(errors="replace")[-400:])
            return None
        return np.load(out)


# ------------------------------------------------------------------ a picture inside (Fusion, 3MF)


def _picture_inside(path: str, size_px: int) -> bytes | None:
    """
    The picture a ZIP-based CAD file carries of itself: one named like a thumbnail or preview if there is one, else
    the biggest picture in it. Fitted to a square on white, like the other previews.
    """
    with zipfile.ZipFile(path) as z:
        pictures = [i for i in z.infolist() if i.filename.lower().endswith(_PICTURE) and 0 < i.file_size < 20_000_000]
        if not pictures:
            return None
        named = [i for i in pictures if any(w in i.filename.lower() for w in ("thumb", "preview", "small"))]
        best = max(named or pictures, key=lambda i: i.file_size)
        img = Image.open(io.BytesIO(z.read(best))).convert("RGBA")
    img.thumbnail((size_px, size_px))
    tile = Image.new("RGBA", (size_px, size_px), (255, 255, 255, 255))
    tile.alpha_composite(img, ((size_px - img.width) // 2, (size_px - img.height) // 2))
    out = io.BytesIO()
    tile.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
