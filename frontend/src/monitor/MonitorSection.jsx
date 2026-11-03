import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, headerButton, primaryButton, uiText } from "../styles.js";
import { errorText, getWebcams } from "../api.js";
import { useData } from "../data.jsx";
import { CameraTile } from "./CameraTile.jsx";
import { arranged, fit, GAP, moved, useRoom } from "./wall.js";

// Every printer's cameras, as set up in Mainsail and played the way Mainsail plays them, in one grid: the pictures
// only, all the same size, each named in its corner. The tiles are as large as they can be while all of them fit in the
// window, and change with it. Click one to see it on its own, filling the window; click again (or Esc) to go back.
// Drag a camera onto another to move it there, then Save layout to keep the new order on the server (order: "printer
// id:camera name" keys; onSave sends one and resolves once the server has it). A camera not in the order yet goes after
// the ones that are. Scroll over a camera to zoom into it, up to maxZoom (chosen beside Save layout; onMaxZoom keeps
// it), and drag a zoomed one to look around. Resync asks every printer for its cameras again and connects to each anew.
const TOOLBAR = 46; // the Save layout line above the grid, with the gap below it
const ZOOMS = [2, 3, 4, 6, 8]; // the max zoom choices; the server takes only these

export function MonitorSection({ order = [], onSave, maxZoom = 4, onMaxZoom }) {
  const { printers } = useData();
  const [cams, setCams] = useState(null); // printer id -> { webcams, error }
  const [big, setBig] = useState(null); // the camera shown on its own: its key
  const [dragging, setDragging] = useState(null); // the key of the camera being dragged
  const [over, setOver] = useState(null); // the key of the camera it would go to
  const [draft, setDraft] = useState(null); // the order as rearranged here, not saved yet (null = as saved)
  const [saving, setSaving] = useState({ phase: "idle" }); // idle | saving | saved | error
  const [round, setRound] = useState(0); // one more for each Resync: the tiles start over, connecting again
  const [resyncing, setResyncing] = useState(false);
  const active = printers.filter((p) => !p.decommissioned);
  const ids = active.map((p) => p.id).join(",");
  const [wall, setWall] = useState(null); // the wall itself, once it's on the page
  const room = useRoom(wall);

  useEffect(() => {
    let live = true;
    Promise.all(active.map((p) => getWebcams(p.id).then((d) => [p.id, d], (e) => [p.id, { webcams: [], error: errorText(e) }])))
      .then((pairs) => {
        if (!live) return;
        setCams(Object.fromEntries(pairs));
        setResyncing(false);
      });
    return () => {
      live = false;
    };
  }, [ids, round]);
  const resync = () => {
    setResyncing(true);
    setRound((r) => r + 1);
  };

  useEffect(() => {
    if (!big) return;
    const close = (e) => e.key === "Escape" && setBig(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [big]);

  // leaving the page with a rearranged layout not saved yet asks first
  useEffect(() => {
    if (!draft) return;
    const ask = (e) => e.preventDefault();
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [draft]);

  if (!cams) return <div style={uiText(13, c.textFaint)}>Finding the printers' cameras…</div>;

  // one tile per camera; a printer with two cameras gets two, named "VT 1190 · Nozzle"
  const tiles = active.flatMap((p) => {
    const list = cams[p.id]?.webcams || [];
    // the printer's own web page (Mainsail, or PrusaLink for a Prusa reached that way), linked from the corner of its tiles
    const prusa = p.connectionType === "prusalink";
    const url = prusa ? p.prusalinkUrl : p.mainsailUrl;
    const link = url ? { url, name: prusa ? "PrusaLink" : "Mainsail", printer: p.name } : null;
    return list.map((cam) => ({ key: `${p.id}:${cam.name}`, label: list.length > 1 ? `${p.name} · ${cam.name}` : p.name, cam, link }));
  });
  // the tiles stay in this one order on the page (moving a playing camera on the page would restart it); where each
  // one shows is set with CSS order instead
  const keys = arranged(tiles.map((t) => t.key), draft || order);
  const place = new Map(keys.map((k, i) => [k, i]));
  const endDrag = () => {
    setDragging(null);
    setOver(null);
  };
  const drop = (target) => {
    if (dragging && target !== dragging) {
      setDraft(moved(keys, dragging, target));
      setSaving({ phase: "idle" });
    }
    endDrag();
  };
  const without = active.filter((p) => !(cams[p.id]?.webcams || []).length);
  const below = (without.length && !big ? 34 : 0) + (tiles.length && !big ? TOOLBAR : 0); // the lines around the grid
  const { cols, width } = fit(big ? 1 : tiles.length, room.width, room.height - below);
  const save = async () => {
    setSaving({ phase: "saving" });
    try {
      await onSave(keys);
      setDraft(null);
      setSaving({ phase: "saved" });
    } catch (e) {
      setSaving({ phase: "error", message: errorText(e) });
    }
  };
  const discard = () => {
    setDraft(null);
    setSaving({ phase: "idle" });
  };

  return (
    <div ref={setWall} data-testid="monitor-section" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {tiles.length === 0 ? (
        <div style={uiText(13, c.textMuted, { lineHeight: 1.6 })}>
          No cameras yet. A printer's camera shows here once it's set up in Mainsail (Settings → Webcams).
        </div>
      ) : (
        !big && (
          <LayoutBar
            changed={!!draft} saving={saving} onSave={save} onDiscard={discard} maxZoom={maxZoom} onMaxZoom={onMaxZoom}
            resyncing={resyncing} onResync={resync}
          />
        )
      )}
      {tiles.length > 0 && (
        <div
          data-testid="monitor-grid"
          style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, ${width}px)`, justifyContent: "center", gap: GAP }}
        >
          {/* all stay mounted while one is enlarged, so no camera has to connect again on the way back */}
          {tiles.map((t) => (
            <CameraTile
              key={`${t.key}#${round}`} label={t.label} cam={t.cam} link={t.link} big={big === t.key} hidden={!!big && big !== t.key}
              place={place.get(t.key)} moving={dragging === t.key} target={over === t.key && dragging !== t.key} maxZoom={maxZoom}
              onClick={() => setBig(big ? null : t.key)}
              drag={big ? null : {
                start: () => setDragging(t.key),
                enter: () => dragging && setOver(t.key),
                drop: () => drop(t.key),
                end: endDrag,
              }}
            />
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

// Above the grid: how to rearrange and zoom, the max zoom, Resync, and Save layout (with Discard) once something has been
// moved
function LayoutBar({ changed, saving, onSave, onDiscard, maxZoom, onMaxZoom, resyncing, onResync }) {
  const busy = saving.phase === "saving";
  const said =
    saving.phase === "error" ? { text: `Not saved: ${saving.message}`, color: c.danger }
    : saving.phase === "saved" ? { text: "Layout saved", color: c.green }
    : changed ? { text: "Layout changed, not saved yet", color: c.amber }
    : { text: "Drag a camera onto another to move it there. Scroll over one to zoom in.", color: c.textFaint };
  return (
    <div data-testid="monitor-layout" style={{ display: "flex", alignItems: "center", gap: 10, minHeight: 32, flexWrap: "wrap" }}>
      <div data-testid="monitor-layout-status" style={uiText(12, said.color, { flex: 1, minWidth: 180 })}>{said.text}</div>
      <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6 })}>
        Max zoom
        <select
          data-testid="monitor-max-zoom" value={maxZoom} onChange={(e) => onMaxZoom?.(Number(e.target.value))}
          style={{ ...headerButton(), height: 32, padding: "0 6px", color: c.textPrimary, background: c.panelAlt }}
        >
          {ZOOMS.map((z) => (
            <option key={z} value={z}>{z}×</option>
          ))}
        </select>
      </label>
      <button
        type="button" data-testid="monitor-resync" onClick={onResync} disabled={resyncing}
        title="Ask every printer for its cameras again and reconnect to each"
        style={{ ...cancelButton(resyncing), display: "flex", alignItems: "center", gap: 6 }}
      >
        <RefreshCw size={13} style={resyncing ? { animation: "fh-spin 1s linear infinite" } : undefined} />
        {resyncing ? "Resyncing…" : "Resync"}
      </button>
      {changed && (
        <button type="button" onClick={onDiscard} disabled={busy} style={cancelButton(busy)}>
          Discard
        </button>
      )}
      <button
        type="button" data-testid="monitor-save" onClick={onSave} disabled={!changed || busy}
        style={{ ...primaryButton(!changed || busy), opacity: changed ? (busy ? 0.7 : 1) : 0.45 }}
      >
        {busy ? "Saving…" : "Save layout"}
      </button>
    </div>
  );
}
