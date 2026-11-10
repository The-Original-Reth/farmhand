import { useEffect, useRef, useState } from "react";
import { Radio } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, panelBox, primaryButton, uiText } from "../styles.js";
import { errorText, getStream, renameSlideshow, saveStream, startStream, stopStream } from "../api.js";
import { useData } from "../data.jsx";
import { usePrintProgress, usePrinterCameras } from "../monitor/cameras.js";
import { StreamPreview } from "./StreamPreview.jsx";
import { YouTubeAccountPanel, YouTubeTextPanel } from "./StreamPanels.jsx";
import { DefaultsPanel } from "./StreamSquares.jsx";
import { SaveChoice, SavedLayoutsPanel, sameAs, shownOf } from "./SavedLayouts.jsx";

// The Stream page: Farmhand sends the printers' cameras live to YouTube (or Twitch) itself, laid out in a grid of
// squares (each a camera, a logo or nothing, with a border round it) or taking turns, with each printer's name and print
// written under its camera. No OBS needed. It can also set the YouTube broadcast's own title and description
// (StreamPanels.jsx). The stream key is typed here once and kept on the server; it never comes back to the page, which
// only knows that one is saved. Cameras are found as on Monitor (cameras.js) and named the same way ("printer id:camera
// name").
const STATUS_EVERY_MS = 5000;
const WHERE_KEY = {
  youtube: "In YouTube Studio: Create → Go live → Stream, then Copy next to Stream key.",
  twitch: "In the Twitch Creator Dashboard: Settings → Stream, then Copy next to Primary Stream key.",
};

const DRAFT_KEY = "farmhand-stream-draft"; // the setup as it was when the stream was turned off (never the stream key)

const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");
const printerOf = (key) => Number(key.slice(0, key.indexOf(":")));
const cameraOf = (key) => key.slice(key.indexOf(":") + 1);

export function StreamSection({ layouts = [], onSaveLayouts, onSlideshowRenamed }) {
  const { printers } = useData();
  const active = printers.filter((p) => !p.decommissioned);
  const [page, setPageFirst] = useState(null); // (set below; here so the switch can quiet the page's other askers)
  const enabled = page?.settings.enabled !== false;
  const onRef = useRef(enabled);
  onRef.current = enabled;
  const { cams } = usePrinterCameras(enabled ? active : []);
  const setPage = setPageFirst; // what the server says: { settings, status, destinations, resolutions, fonts, media, youtube }
  const [draft, setDraft] = useState(null); // the choices as changed here, not saved yet (null = as saved)
  const [key, setKey] = useState(""); // a stream key typed here, not saved yet
  const [busy, setBusy] = useState(null); // "save" | "start" | "stop" | "logo" | "youtube" while the server is asked
  const [problem, setProblem] = useState(null); // what the server last refused, and why
  const [choosing, setChoosing] = useState(false); // Save asking: a new layout, or over one there is
  const [fromLayout, setFromLayout] = useState(null); // the saved layout last used or saved here: Save suggests overwriting it
  const [loadError, setLoadError] = useState(null);

  const draftOrSaved = draft || page?.settings;
  const inGrid = (draftOrSaved?.cells || []).filter((x) => x?.camera).map((x) => x.camera);
  const progress = usePrintProgress(enabled && draftOrSaved?.showStatus ? [...new Set(inGrid.map(printerOf))] : [], { keepErrors: true });

  useEffect(() => {
    let live = true;
    // turned off, the page doesn't ask again until it's turned on (it was asked once, to know)
    const ask = (first) =>
      !document.hidden && (first === true || onRef.current) &&
      getStream()
        .then((p) => live && (setPage(p), setLoadError(null)))
        .catch((e) => live && setLoadError(errorText(e)));
    ask(true);
    const timer = setInterval(ask, STATUS_EVERY_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  if (!page) {
    return <div style={uiText(13, loadError ? c.danger : c.textFaint)}>{loadError ? `Couldn't load the stream: ${loadError}` : "Loading…"}</div>;
  }

  const saved = page.settings;
  const shown = draft || saved;
  const changed = !!draft || key.trim() !== "";
  const change = (what) => {
    setDraft({ ...shown, ...what });
    setProblem(null);
  };

  // every camera there is, as on Monitor: printer by printer
  const label = (k) => {
    const id = printerOf(k);
    const p = printers.find((x) => x.id === id);
    const many = (cams[id]?.webcams || []).length > 1;
    return p ? (many ? `${p.name} · ${cameraOf(k)}` : p.name) : `Printer ${id} · ${cameraOf(k)}`;
  };
  const cameras = active.flatMap((p) => (cams[p.id]?.webcams || []).map((cam) => ({ key: `${p.id}:${cam.name}` }))).map((x) => ({ ...x, label: label(x.key) }));
  const finding = active.some((p) => !cams[p.id] || cams[p.id].kept);

  const ask = async (what, call) => {
    setBusy(what);
    setProblem(null);
    try {
      const p = await call();
      setPage(p);
      return p;
    } catch (e) {
      setProblem(errorText(e));
      return null;
    } finally {
      setBusy(null);
    }
  };
  // a slideshow renamed (its folder on the server, and the saved squares and layouts showing it): squares changed here
  // and not saved yet follow too. The page as the server answered, or null when it couldn't.
  const renameShow = async (old, name) => {
    const p = await ask("picture", () => renameSlideshow(old, name));
    if (!p) return null;
    setDraft((d) => d && { ...d, cells: d.cells.map((x) => (x && !x.camera && x.slideshow === old ? { ...x, slideshow: name } : x)) });
    onSlideshowRenamed?.(old, name);
    return p;
  };
  // everything on the page that's saved with Save (a blank number box is sent as it is, for the server to say why not)
  const sendAll = () =>
    saveStream({
      destination: shown.destination, cols: shown.cols, rows: shown.rows, cells: shown.cells, showStatus: shown.showStatus, layout: shown.layout,
      resolution: shown.resolution, secondsAll: shown.secondsAll === "" ? -1 : shown.secondsAll, secondsEach: shown.secondsEach === "" ? -1 : shown.secondsEach,
      borderColor: shown.borderColor, background: shown.background, font: shown.font, color: shown.color, title: shown.title, description: shown.description, streamKey: key.trim(),
    });
  // Save: the stream's settings, and the layout under the name chosen (a new one, or over one there is)
  const saveWithLayout = async ({ name, list }) => {
    const p = await ask("save", sendAll);
    if (!p) return false;
    setDraft(null);
    setKey("");
    try {
      await onSaveLayouts(list);
    } catch (e) {
      setProblem(`The settings were saved, but not the layout: ${errorText(e)}`);
      return false;
    }
    setFromLayout(name);
    setChoosing(false);
    return true;
  };
  // Save in a square's editor: the stream's settings now (as Go live saves them), no layout asked for
  const saveNow = async () => {
    const p = await ask("save", sendAll);
    if (!p) return;
    setDraft(null);
    setKey("");
  };
  // The switch at the top. Off: the stream stops and the page rests (no cameras, nothing asked of the printers), the
  // setup as it is here (saved or not, but never a stream key typed) kept in this browser; on: that setup comes back.
  const turn = async (on) => {
    if (!on) {
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
      } catch {
        // (a browser that keeps nothing: the unsaved setup is lost when turned off)
      }
      if (await ask("save", () => saveStream({ enabled: false }))) {
        setDraft(null);
        setKey("");
      }
      return;
    }
    if (!(await ask("save", () => saveStream({ enabled: true })))) return;
    try {
      const kept = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
      if (kept) setDraft(kept);
      localStorage.removeItem(DRAFT_KEY);
    } catch {
      // (nothing kept: the saved setup)
    }
  };
  const forgetKey = () => ask("save", () => saveStream({ clearKey: true }));
  const start = async () => {
    if (changed) {
      const p = await ask("save", sendAll);
      if (!p) return;
      setDraft(null);
      setKey("");
    }
    ask("start", startStream);
  };
  const stop = () => ask("stop", stopStream);
  // Switch to a saved layout: the stream takes it now (while live, it starts again with it). Anything else changed on
  // the page and not saved yet stays as it is, still to be saved.
  const switchTo = async (l) => {
    const fields = shownOf(l);
    const p = await ask("save", () => saveStream(fields));
    if (!p) return false;
    setFromLayout(l.name);
    if (draft) {
      const next = { ...shown, ...fields };
      const same = Object.keys(p.settings).every((k) => JSON.stringify(p.settings[k]) === JSON.stringify(next[k]));
      setDraft(same ? null : next);
    }
    return true;
  };

  const status = page.status;
  const destLabel = (k) => page.destinations.find((d) => d.key === k)?.label || k;
  // the grid's squares as the preview plays them
  const squares = shown.cells.map((cell) => {
    if (cell?.camera) {
      const id = printerOf(cell.camera);
      const cam = (cams[id]?.webcams || []).find((x) => x.name === cameraOf(cell.camera)) || null;
      return { type: "camera", key: cell.camera, label: label(cell.camera), cam, print: progress[id] || null, background: cell.background || null, cell };
    }
    return cell ? { type: "card", cell } : null;
  });

  const head = <StreamSwitch on={enabled} onTurn={turn} busy={!!busy} />;
  if (!enabled) {
    return (
      <div data-testid="stream-section" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {head}
        <div data-testid="stream-off" style={panelBox({ padding: 16, maxWidth: 640 })}>
          <div style={uiText(14, c.heading, { fontWeight: 600 })}>The stream is off</div>
          <div style={uiText(12, c.textMuted, { marginTop: 6, lineHeight: 1.6 })}>
            Nothing is streamed, no cameras play on this page and it doesn't ask the printers anything. Turn it on to carry on
            where you left off, with the setup as it was, saved or not.
          </div>
        </div>
        {problem && <div data-testid="stream-problem" style={uiText(13, c.danger, { lineHeight: 1.5 })}>{problem}</div>}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
    {head}
    <div data-testid="stream-section" style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(340px, 2fr)", gap: 20, alignItems: "start" }}>
      {/* left: what the stream looks like; right: going live and what goes into it */}
      <div style={{ minWidth: 0, position: "sticky", top: 0 }}>
        <StreamPreview
          shown={shown} change={change} squares={squares} showStatus={shown.showStatus} live={status.live} resolutions={page.resolutions}
          cameras={cameras} media={page.media} fonts={page.fonts} label={label}
          ask={ask} busy={busy} onSave={saveNow} dirty={changed} onRenameSlideshow={renameShow}
          serverClock={status.serverTime !== null && !changed ? { serverTime: status.serverTime, heardAt: status.heardAt, live: status.onAir } : null}
          cycle={shown.layout === "cycle" ? { all: Number(shown.secondsAll) || 0, each: Math.max(1, Number(shown.secondsEach) || 0) } : null}
        />
      </div>
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
        {/* on air or not, and the button that changes it */}
        <div data-testid="stream-status" style={panelBox({ padding: 16, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" })}>
          <Radio size={20} color={status.live ? (status.error ? c.amber : c.green) : c.textFaint} />
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={uiText(15, c.heading, { fontWeight: 600 })}>
              {status.live
                ? status.error ? "Reconnecting…" : `Live on ${destLabel(status.destination)} since ${timeOf(status.startedAt)}${status.encoder === "nvenc" ? " · on the NVIDIA card" : status.encoder === "cpu" ? " · on the processor" : ""}`
                : "Not streaming"}
            </div>
            <div style={uiText(12, status.error ? c.amber : c.textMuted, { marginTop: 4, lineHeight: 1.5 })}>
              {status.error
                ? status.error
                : status.live
                  ? `${status.cameras.length} camera${status.cameras.length === 1 ? "" : "s"}: ${status.cameras.join(", ")}`
                  : `Farmhand sends the grid below to ${destLabel(shown.destination)} itself, no OBS needed.`}
            </div>
          </div>
          {status.live ? (
            <button type="button" data-testid="stream-stop" onClick={stop} disabled={!!busy} style={{ ...cancelButton(!!busy), color: c.danger, borderColor: c.danger }}>
              {busy === "stop" ? "Stopping…" : "Stop stream"}
            </button>
          ) : (
            <button type="button" data-testid="stream-start" onClick={start} disabled={!!busy} style={primaryButton(!!busy)}>
              {busy === "start" ? "Going live…" : "Go live"}
            </button>
          )}
        </div>
        {problem && (
          <div data-testid="stream-problem" style={uiText(13, c.danger, { lineHeight: 1.5 })}>
            {problem}
          </div>
        )}

        {/* the YouTube broadcast's own title and description */}
        {shown.destination === "youtube" && <YouTubeTextPanel shown={shown} change={change} status={status} />}

        {/* where it goes */}
        <div style={panelBox({ padding: 16, display: "flex", flexDirection: "column", gap: 12 })}>
          <div style={uiText(14, c.heading, { fontWeight: 600 })}>Where to</div>
          <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 10 })}>
            <span style={{ width: 90 }}>Stream to</span>
            <select
              data-testid="stream-destination" value={shown.destination} onChange={(e) => change({ destination: e.target.value })}
              style={{ ...fieldBox(), padding: "6px 8px" }}
            >
              {page.destinations.map((d) => (
                <option key={d.key} value={d.key}>{d.label}</option>
              ))}
            </select>
          </label>
          <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" })}>
            <span style={{ width: 90 }}>Stream key</span>
            <input
              data-testid="stream-key" type="password" autoComplete="off" value={key} onChange={(e) => (setKey(e.target.value), setProblem(null))}
              placeholder={saved.keySet ? "Saved. Type a new one to replace it" : "Paste your stream key"}
              style={{ ...fieldBox(), padding: "6px 8px", flex: 1, minWidth: 240 }}
            />
            {saved.keySet && (
              <button type="button" data-testid="stream-forget-key" onClick={forgetKey} disabled={!!busy} style={headerButton()}>
                Forget key
              </button>
            )}
          </label>
          <div style={uiText(12, c.textFaint, { lineHeight: 1.5 })}>
            {WHERE_KEY[shown.destination]} The key stays in Farmhand: it isn't shown again or written to the settings copy.
          </div>
        </div>

        {/* signing in to YouTube, for the title and description */}
        {shown.destination === "youtube" && <YouTubeAccountPanel youtube={page.youtube} status={status} ask={ask} busy={busy} />}

        <DefaultsPanel shown={shown} change={change} cameras={cameras} finding={finding && !cameras.length} count={inGrid.length} fonts={page.fonts} />
        <SavedLayoutsPanel
          layouts={layouts} onSave={onSaveLayouts} saved={saved} label={label} switchTo={switchTo}
        />
        {choosing ? (
          <SaveChoice
            layouts={layouts} shown={shown} busy={busy === "save"} onConfirm={saveWithLayout} onCancel={() => setChoosing(false)}
            suggested={fromLayout || layouts.find((l) => sameAs(l, saved))?.name}
          />
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={uiText(12, changed ? c.amber : c.textFaint, { flex: 1 })}>
              {changed ? (status.live ? "Not saved yet. Saving changes the stream as it goes out." : "Not saved yet.") : "Saved. Save again to keep this as a layout."}
            </div>
            {changed && (
              <button type="button" onClick={() => (setDraft(null), setKey(""), setProblem(null))} disabled={!!busy} style={cancelButton(!!busy)}>
                Discard
              </button>
            )}
            <button type="button" data-testid="stream-save" onClick={() => (setChoosing(true), setProblem(null))} disabled={!!busy} style={primaryButton(!!busy)}>
              Save
            </button>
          </div>
        )}
      </div>
    </div>
    </div>
  );
}

// The switch at the top of the page: the stream's functions on or off
function StreamSwitch({ on, onTurn, busy }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span style={uiText(14, c.heading, { fontWeight: 600 })}>Stream</span>
      <button
        type="button" role="switch" aria-checked={on} data-testid="stream-switch" disabled={busy} onClick={() => onTurn(!on)}
        title={on ? "Turn the stream off: it stops, and the page rests" : "Turn the stream on, as it was"}
        style={{
          position: "relative", width: 40, height: 22, borderRadius: 11, border: `1px solid ${on ? c.green : c.borderStrong}`, padding: 0,
          background: on ? c.green : c.panelAlt, cursor: busy ? "default" : "pointer", flexShrink: 0,
        }}
      >
        <span style={{ position: "absolute", top: 2, left: on ? 20 : 2, width: 16, height: 16, borderRadius: 8, background: on ? c.bg : c.textMuted, transition: "left 0.15s" }} />
      </button>
      <span style={uiText(12, on ? c.textMuted : c.textFaint)}>{on ? "On" : "Off"}</span>
    </div>
  );
}
