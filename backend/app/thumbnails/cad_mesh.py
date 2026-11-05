"""
Turn a STEP / IGES / BREP file into triangles for its preview, with gmsh (which carries OpenCascade):

    python -m app.thumbnails.cad_mesh <file> <out.npy>

Run as its own process by cad_preview.py, so a file OpenCascade struggles with can only stop this, never the API. The
triangles are written as a float32 array (n, 3, 3). Fine enough for a 256px picture: about 40 steps across the part,
with curved faces followed more closely.
"""
from __future__ import annotations

import sys

import numpy as np


def mesh(path: str) -> np.ndarray:
    import gmsh  # only here: the API itself never loads it

    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.importShapes(path)
        gmsh.model.occ.synchronize()
        x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(-1, -1)
        size = max(x1 - x0, y1 - y0, z1 - z0) or 1.0
        gmsh.option.setNumber("Mesh.MeshSizeMax", size / 40)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
        gmsh.option.setNumber("Mesh.Algorithm", 6)  # Frontal-Delaunay: quick and steady on CAD faces
        gmsh.model.mesh.generate(2)

        tags, coords, _ = gmsh.model.mesh.getNodes()
        index = np.zeros(int(tags.max()) + 1, dtype=np.int64)
        index[tags.astype(np.int64)] = np.arange(len(tags))
        points = coords.reshape(-1, 3).astype(np.float32)
        tris = []
        for kind, _, nodes in zip(*gmsh.model.mesh.getElements(2)):
            if kind == 2:  # 3-node triangles
                tris.append(index[nodes.astype(np.int64)].reshape(-1, 3))
        if not tris:
            raise ValueError("No surfaces to draw")
        return points[np.concatenate(tris)]
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    np.save(out, mesh(src))
