import { useEffect, useRef, useState } from "react";
import { c, fs, ui } from "../theme.js";
import { CameraPicture } from "./players.jsx";
import { NO_ZOOM, panned, TILE, zoomed } from "./wall.js";

// A camera's own picture, turned and flipped as Mainsail is set to show it. Scroll over it to zoom in (up to maxZoom)
// or out; drag a zoomed one to look around; the badge in the corner goes back to the whole picture.
export function CameraTile({ label, cam, big, hidden, place, moving, target, drag, maxZoom = 4, onClick }) {
  const [state, setState] = useState("waiting"); // waiting | showing | failed
  const [el, setEl] = useState(null);
  const [zoom, setZoom] = useState(NO_ZOOM);
  const pan = useRef(null); // while dragging a zoomed picture: where it started, and whether it has moved
  const z = zoom.s > maxZoom ? zoomed(zoom, maxZoom / zoom.s, 0.5, 0.5, maxZoom) : zoom; // a lower max zooms back out
  const turn = [
    cam.rotation ? `rotate(${cam.rotation}deg)` : "",
    cam.flip_horizontal ? "scaleX(-1)" : "",
    cam.flip_vertical ? "scaleY(-1)" : "",
  ].join(" ").trim();
  const fill = { width: "100%", height: "100%", objectFit: "contain", display: "block", border: 0, transform: turn || undefined };

  // a native listener, as React's can't stop the page scrolling under the wheel
  useEffect(() => {
    if (!el) return;
    const wheel = (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const delta = Math.max(-300, Math.min(300, e.deltaY * (e.deltaMode === 1 ? 33 : 1))); // lines (Firefox) to pixels
      setZoom((now) => zoomed(now, Math.exp(-delta * 0.002), (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height, maxZoom));
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [el, maxZoom]);

  const startPan = (e) => {
    if (z.s === 1 || e.button !== 0) return;
    pan.current = { x: e.clientX, y: e.clientY, from: z, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const movePan = (e) => {
    const p = pan.current;
    if (!p) return;
    const r = el.getBoundingClientRect();
    if (Math.abs(e.clientX - p.x) + Math.abs(e.clientY - p.y) > 4) p.moved = true;
    setZoom(panned(p.from, (e.clientX - p.x) / r.width, (e.clientY - p.y) / r.height));
  };
  const endPan = () => {
    // a drag that moved the picture isn't also a click
    if (pan.current?.moved) setTimeout(() => (pan.current = null));
    else pan.current = null;
  };
  const click = () => !pan.current?.moved && onClick();

  return (
    <div
      ref={setEl}
      data-testid="monitor-camera"
      role="button"
      tabIndex={0}
      onClick={click}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onClick())}
      onPointerDown={startPan}
      onPointerMove={movePan}
      onPointerUp={endPan}
      onPointerCancel={endPan}
      title={big ? "Back to all cameras. Scroll to zoom" : `See ${label} on its own, scroll to zoom, or drag it to move it`}
      draggable={!!drag && z.s === 1}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", label);
        drag?.start();
      }}
      onDragEnter={() => drag?.enter()}
      onDragOver={(e) => drag && e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        drag?.drop();
      }}
      onDragEnd={() => drag?.end()}
      style={{
        position: "relative", aspectRatio: `${TILE}`,
        display: hidden ? "none" : undefined, order: place, opacity: moving ? 0.4 : 1,
        outline: target ? `2px solid ${c.amber}` : "none", outlineOffset: 2,
        background: "#000", border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden",
        cursor: z.s > 1 ? (pan.current ? "grabbing" : "grab") : big ? "zoom-out" : "zoom-in", touchAction: z.s > 1 ? "none" : undefined,
      }}
    >
      <div
        data-testid="monitor-zoomed"
        style={{
          position: "absolute", inset: 0, transformOrigin: "0 0",
          transform: z.s > 1 ? `translate(${z.x * 100}%, ${z.y * 100}%) scale(${z.s})` : undefined,
        }}
      >
        <CameraPicture cam={cam} label={label} style={fill} onState={setState} />
      </div>
      {/* over the picture, so the wheel, drags and clicks reach the tile even where the camera is a page of its own */}
      <div style={{ position: "absolute", inset: 0 }} />
      {state !== "showing" && (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", ...ui, fontSize: fs(12), color: "#8a9198" }}>
          {state === "failed" ? "The camera isn't answering" : "Waiting for the camera…"}
        </div>
      )}
      {z.s > 1 && (
        <button
          type="button"
          data-testid="monitor-zoom-reset"
          title="Back to the whole picture"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            setZoom(NO_ZOOM);
          }}
          style={{
            position: "absolute", right: 6, top: 6, padding: "2px 7px", borderRadius: 3, background: "rgba(0,0,0,0.55)",
            color: "#e6e8ea", border: "none", ...ui, fontSize: fs(11), cursor: "pointer",
          }}
        >
          {z.s.toFixed(1)}× ✕
        </button>
      )}
      <div
        style={{
          position: "absolute", left: 6, bottom: 6, padding: "2px 7px", borderRadius: 3, background: "rgba(0,0,0,0.55)",
          color: "#e6e8ea", ...ui, fontSize: fs(11), pointerEvents: "none",
        }}
      >
        {label}
      </div>
    </div>
  );
}
