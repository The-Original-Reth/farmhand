import { useEffect, useState } from "react";
import { c, fs, ui } from "../theme.js";
import { uiText } from "../styles.js";
import { errorText, getWebcams } from "../api.js";
import { useData } from "../data.jsx";

const SNAPSHOT_EVERY_MS = 3000; // a camera without a plain MJPEG stream is shown from its snapshots, this often

// Every printer's cameras (as set up in Mainsail) in one grid, the pictures only, each named in its corner. Click
// one to see it on its own, large; click again (or Esc) to go back to the grid.
export function MonitorSection() {
  const { printers } = useData();
  const [cams, setCams] = useState(null); // printer id -> { webcams, error }
  const [big, setBig] = useState(null); // the camera shown on its own: its key
  const active = printers.filter((p) => !p.decommissioned);
  const ids = active.map((p) => p.id).join(",");

  useEffect(() => {
    let live = true;
    Promise.all(active.map((p) => getWebcams(p.id).then((d) => [p.id, d], (e) => [p.id, { webcams: [], error: errorText(e) }])))
      .then((pairs) => live && setCams(Object.fromEntries(pairs)));
    return () => {
      live = false;
    };
  }, [ids]);

  useEffect(() => {
    if (!big) return;
    const close = (e) => e.key === "Escape" && setBig(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [big]);

  if (!cams) return <div style={uiText(13, c.textFaint)}>Finding the printers' cameras…</div>;

  // one tile per camera; a printer with two cameras gets two, named "VT 1190 · Nozzle"
  const tiles = active.flatMap((p) => {
    const list = cams[p.id]?.webcams || [];
    return list.map((cam, i) => ({ key: `${p.id}-${i}`, label: list.length > 1 ? `${p.name} · ${cam.name}` : p.name, cam }));
  });
  const without = active.filter((p) => !(cams[p.id]?.webcams || []).length);
  const shown = big ? tiles.filter((t) => t.key === big) : tiles;

  return (
    <div data-testid="monitor-section" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {tiles.length === 0 ? (
        <div style={uiText(13, c.textMuted, { lineHeight: 1.6 })}>
          No cameras yet. A printer's camera shows here once it's set up in Mainsail (Settings → Webcams).
        </div>
      ) : (
        <div
          data-testid="monitor-grid"
          style={{ display: "grid", gridTemplateColumns: big ? "1fr" : "repeat(auto-fill, minmax(340px, 1fr))", gap: 8 }}
        >
          {shown.map((t) => (
            <CameraTile key={t.key} label={t.label} cam={t.cam} big={!!big} onClick={() => setBig(big ? null : t.key)} />
          ))}
        </div>
      )}
      {without.length > 0 && !big && (
        <div data-testid="monitor-without" style={uiText(12, c.textFaint, { lineHeight: 1.7 })}>
          No camera:{" "}
          {without.map((p, i) => (
            <span key={p.id} title={cams[p.id]?.error || "No camera set up in Mainsail"}>
              {i > 0 && ", "}
              {p.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// A camera's own picture, turned and flipped as Mainsail is set to show it
function CameraTile({ label, cam, big, onClick }) {
  const [w, h] = String(cam.aspect_ratio || "16:9").split(":").map(Number);
  const src = useCameraPicture(cam);
  const [failed, setFailed] = useState(false);
  const turn = [
    cam.rotation ? `rotate(${cam.rotation}deg)` : "",
    cam.flip_horizontal ? "scaleX(-1)" : "",
    cam.flip_vertical ? "scaleY(-1)" : "",
  ].join(" ").trim();

  useEffect(() => setFailed(false), [src]);

  return (
    <div
      data-testid="monitor-camera"
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onClick())}
      title={big ? "Back to all cameras" : `See ${label} on its own`}
      style={{
        position: "relative", aspectRatio: w && h ? `${w} / ${h}` : "16 / 9", maxHeight: big ? "calc(100vh - 170px)" : undefined,
        background: "#000", border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden", cursor: big ? "zoom-out" : "zoom-in",
      }}
    >
      {src && !failed && (
        <img
          src={src}
          alt={label}
          onError={() => setFailed(true)}
          style={{ width: "100%", height: "100%", objectFit: "contain", display: "block", transform: turn || undefined }}
        />
      )}
      {(failed || !src) && (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", ...ui, fontSize: fs(12), color: "#8a9198" }}>
          {src ? "The camera isn't answering" : "Waiting for the camera…"}
        </div>
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

// What to show: a plain MJPEG stream as it is (the browser keeps it moving), otherwise the snapshot, fetched again every
// few seconds. The next snapshot is loaded before it replaces the last, so the picture never blanks in between.
function useCameraPicture(cam) {
  const snapshot = cam.snapshot_url;
  const stream = cam.mjpeg ? cam.stream_url : null;
  const [src, setSrc] = useState(stream);

  useEffect(() => {
    if (stream) return setSrc(stream);
    if (!snapshot) return setSrc(null);
    let live = true;
    let timer;
    const fresh = () => (/^https?:/i.test(snapshot) ? `${snapshot}${snapshot.includes("?") ? "&" : "?"}t=${Date.now()}` : snapshot);
    const next = () => {
      const url = fresh();
      const img = new Image();
      img.onload = () => live && setSrc(url);
      img.onerror = () => live && setSrc((s) => s ?? url); // let the tile say it isn't answering
      img.src = url;
      timer = setTimeout(() => live && next(), SNAPSHOT_EVERY_MS);
    };
    next();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [stream, snapshot]);

  return src;
}
