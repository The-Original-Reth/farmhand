import { useEffect, useState } from "react";

// How the Monitor wall is laid out: every tile one shape, as large as fits, in the order kept on the server.

export const TILE = 16 / 9; // every tile is this shape; a camera of another shape sits in it with black bars
export const GAP = 8;
const SMALLEST = 260; // narrower than this, the tiles stop shrinking to fit and the page scrolls instead

// The keys in the order kept, then any not in it yet in the order they come (a new camera, a new printer)
export function arranged(keys, order) {
  const here = new Set(keys);
  const kept = order.filter((k) => here.has(k));
  return [...kept, ...keys.filter((k) => !kept.includes(k))];
}

// The space the wall has: the page's width, and the window's height below where the wall starts. Kept up to date as
// the window changes size.
export function useRoom(el) {
  const [room, setRoom] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setRoom({ width: Math.floor(r.width), height: Math.floor(window.innerHeight - r.top - 24) });
    };
    measure();
    const seen = new ResizeObserver(measure);
    seen.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      seen.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [el]);
  return room;
}

// How many columns, and how wide each tile: the largest tiles with which all n fit in the room. Tiles never go below
// SMALLEST (or the room's width, if that's less); past that they keep that size and the page scrolls.
export function fit(n, width, height) {
  if (!n || !width) return { cols: 1, width: Math.max(width, 0) };
  let best = { cols: 1, width: 0 };
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    const w = Math.min((width - GAP * (cols - 1)) / cols, ((height - GAP * (rows - 1)) / rows) * TILE);
    if (w > best.width) best = { cols, width: w };
  }
  const floor = Math.min(SMALLEST, width);
  if (best.width < floor) {
    const cols = Math.max(1, Math.floor((width + GAP) / (floor + GAP)));
    return { cols, width: Math.floor((width - GAP * (cols - 1)) / cols) };
  }
  return { cols: best.cols, width: Math.floor(best.width) };
}

// The order after the camera `dragged` is dropped on `target`: it takes the target's place, and the ones between move
// along one to make room.
export function moved(keys, dragged, target) {
  const next = keys.filter((k) => k !== dragged);
  next.splice(keys.indexOf(target), 0, dragged);
  return next;
}

// Zoom on one camera: s is how far in, x and y how far the picture is moved, as shares of the tile (from 1 - s to 0,
// so the picture always covers the tile)
export const NO_ZOOM = { s: 1, x: 0, y: 0 };
const within = (v, s) => Math.min(0, Math.max(1 - s, v));

// The zoom after zooming in (by > 1) or out about the point (px, py), as shares of the tile, so that point stays put
export function zoomed(z, by, px, py, max) {
  const s = Math.min(max, Math.max(1, z.s * by));
  if (s < 1.01) return NO_ZOOM;
  const k = s / z.s;
  return { s, x: within(px - (px - z.x) * k, s), y: within(py - (py - z.y) * k, s) };
}

// The zoom moved by (dx, dy), as shares of the tile, from where it was (`from`)
export function panned(from, dx, dy) {
  return { s: from.s, x: within(from.x + dx, from.s), y: within(from.y + dy, from.s) };
}
