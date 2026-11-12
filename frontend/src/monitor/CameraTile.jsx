import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, PictureInPicture2 } from "lucide-react";
import { c, fs, ui, fixed } from "../theme.js";
import { CameraPicture } from "./players.jsx";
import { NO_ZOOM, panned, TILE, zoomed } from "./wall.js";
import { cameraSource, liveText, same, ustreamerStateUrl, useUstreamerState } from "./liveInfo.js";

// Picture-in-picture: a small window that stays on top of every other one (Chrome and Edge's Document
// Picture-in-Picture), so it works for every kind of camera, not just the ones that are video
const canFloat = typeof window !== "undefined" && "documentPictureInPicture" in window;

// The labels and buttons over a camera's corners: light on a dark see-through backing, readable over any picture
const badge = (more) => ({
  padding: "2px 7px", borderRadius: 3, background: fixed.cameraBadge, color: fixed.cameraText, border: "none", ...ui, fontSize: fs(11), ...more,
});
const corner = (where) => ({ position: "absolute", [where.x]: 6, [where.y]: 6 });

// A press on a corner button isn't also a click on the camera (enlarging it) or the start of a drag
const keepToItself = (e) => e.stopPropagation();
const pressed = (act) => (e) => {
  e.stopPropagation();
  act();
};

// The camera in its own picture-in-picture window while it's open (null until then). The tile shows a note instead,
// so the camera isn't streamed twice. `refused`: the browser wouldn't open one just now (another is open from a
// different tab, or it can't open windows at all).
function useFloating(label) {
  const [win, setWin] = useState(null);
  const [refused, setRefused] = useState(false);
  useEffect(() => () => win?.close(), [win]); // leaving Monitor closes it
  useEffect(() => {
    if (!refused) return;
    const t = setTimeout(() => setRefused(false), 4000);
    return () => clearTimeout(t);
  }, [refused]);
  const open = async () => {
    if (win) return win.close();
    let w;
    try {
      w = await window.documentPictureInPicture.requestWindow({ width: 480, height: 270 });
    } catch {
      return setRefused(true);
    }
    w.document.title = label;
    w.document.body.style.cssText = `margin:0;background:${fixed.camera};overflow:hidden;width:100vw;height:100vh`;
    w.addEventListener("pagehide", () => setWin(null));
    setWin(w);
  };
  return { win, refused, open };
}

// A camera's own picture, turned and flipped as Mainsail is set to show it. Scroll over it to zoom in (up to maxZoom)
// or out; drag a zoomed one to look around; the badge in the corner goes back to the whole picture. The button in the
// top left corner floats it in a picture-in-picture window (where the browser can). `link`: the printer's own web page,
// { url, name, printer } (Mainsail or PrusaLink), opened in a new tab from the bottom right corner. `board`: the
// computer the printer runs on ({ name: "Pi 4", model, memory_gb }), named in the top right corner. `print`: the print
// under way ({ state: "printing" | "paused", progress, file }), its percentage shown left of the board. In the top left corner, beside the
// picture-in-picture button, what the camera runs on and the size and frame rate it is sending, measured live (liveInfo.js).
export function CameraTile({ label, cam, link, board, print, big, hidden, place, moving, target, drag, maxZoom = 4, onClick }) {
  const [state, setState] = useState("waiting"); // waiting | showing | failed
  const [el, setEl] = useState(null);
  const [zoom, setZoom] = useState(NO_ZOOM);
  const pan = useRef(null); // while dragging a zoomed picture: where it started, and whether it has moved
  const floating = useFloating(label);
  const [measured, setMeasured] = useState(null); // what this browser sees of the picture
  const own = useUstreamerState(ustreamerStateUrl(cam)); // what Crowsnest's ustreamer says it is capturing
  const measure = useRef((m) => setMeasured((now) => (same(now, m) ? now : m))).current;
  const live = own || (state === "showing" ? measured : null);
  const source = cameraSource(cam, !!own);
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
        background: fixed.camera, border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden",
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
        {!floating.win && <CameraPicture cam={cam} label={label} style={fill} onState={setState} onMeasure={measure} />}
      </div>
      {floating.win && createPortal(<CameraPicture cam={cam} label={label} style={fill} onState={setState} onMeasure={measure} />, floating.win.document.body)}
      {/* over the picture, so the wheel, drags and clicks reach the tile even where the camera is a page of its own */}
      <div style={{ position: "absolute", inset: 0 }} />
      {(floating.win || floating.refused || state !== "showing") && (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", ...ui, fontSize: fs(12), color: fixed.cameraMessage }}>
          {floating.win ? "In a picture-in-picture window" : floating.refused ? "The browser wouldn't open a picture-in-picture window" : state === "failed" ? "The camera isn't answering" : "Waiting for the camera…"}
        </div>
      )}
      <div style={{ ...corner({ x: "left", y: "top" }), display: "flex", gap: 6, alignItems: "center" }}>
      {canFloat && (
        <button
          type="button"
          data-testid="monitor-pip"
          aria-pressed={!!floating.win}
          title={floating.win ? "Bring it back from picture-in-picture" : "Picture-in-picture: float it in a small window on top of everything"}
          onPointerDown={keepToItself}
          onClick={pressed(floating.open)}
          style={badge({ padding: "3px 6px", cursor: "pointer", display: "flex", alignItems: "center" })}
        >
          <PictureInPicture2 size={14} />
        </button>
      )}
      {source && (
        <div
          data-testid="monitor-live"
          title={own
            ? "What Crowsnest's camera streamer is capturing right now, as it reports it"
            : "Measured live in this browser: the picture's size and the frames arriving each second"}
          style={badge({ fontSize: fs(10) })}
        >
          {liveText(source, live)}
        </div>
      )}
      </div>
      {(z.s > 1 || board || print) && (
        <div style={{ ...corner({ x: "right", y: "top" }), display: "flex", gap: 6, alignItems: "center" }}>
          {z.s > 1 && (
            <button
              type="button"
              data-testid="monitor-zoom-reset"
              title="Back to the whole picture"
              onPointerDown={keepToItself}
              onClick={pressed(() => setZoom(NO_ZOOM))}
              style={badge({ cursor: "pointer" })}
            >
              {z.s.toFixed(1)}× ✕
            </button>
          )}
          {print && (
            <div
              data-testid="monitor-progress"
              title={`${print.state === "paused" ? "Paused" : "Printing"}${print.file ? ` ${print.file}` : ""}`}
              style={badge()}
            >
              {print.state === "paused" ? "Paused " : ""}
              {Math.floor(print.progress || 0)}%
            </div>
          )}
          {board && (
            <div
              data-testid="monitor-board"
              title={[board.model || board.name, board.memory_gb && `${board.memory_gb} GB`].filter(Boolean).join(", ")}
              style={badge()}
            >
              {board.name}
            </div>
          )}
        </div>
      )}
      <div style={badge({ ...corner({ x: "left", y: "bottom" }), pointerEvents: "none" })}>{label}</div>
      {link && (
        <a
          data-testid="monitor-web-ui"
          href={link.url}
          target="_blank"
          rel="noreferrer"
          draggable={false}
          title={`Open ${link.printer}'s ${link.name} in a new tab (${link.url})`}
          onPointerDown={keepToItself}
          onClick={keepToItself}
          style={badge({ ...corner({ x: "right", y: "bottom" }), textDecoration: "none", display: "flex", alignItems: "center", gap: 4 })}
        >
          <ExternalLink size={11} />
          {link.name}
        </a>
      )}
    </div>
  );
}
