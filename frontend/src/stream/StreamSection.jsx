import { useEffect, useState } from "react";
import { Radio } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, panelBox, primaryButton, uiText } from "../styles.js";
import { errorText, getStream, saveStream, startStream, stopStream } from "../api.js";
import { useData } from "../data.jsx";
import { usePrintProgress, usePrinterCameras } from "../monitor/cameras.js";
import { StreamPreview } from "./StreamPreview.jsx";
import { LayoutPanel, YouTubeAccountPanel, YouTubeTextPanel } from "./StreamPanels.jsx";
import { SquaresPanel } from "./StreamSquares.jsx";
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

const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");
const printerOf = (key) => Number(key.slice(0, key.indexOf(":")));
const cameraOf = (key) => key.slice(key.indexOf(":") + 1);

export function StreamSection({ layouts = [], onSaveLayouts }) {
  const { printers } = useData();
  const active = printers.filter((p) => !p.decommissioned);
  const { cams } = usePrinterCameras(active);
  const [page, setPage] = useState(null); // what the server says: { settings, status, destinations, resolutions, logos, youtube }
  const [draft, setDraft] = useState(null); // the choices as changed here, not saved yet (null = as saved)
  const [key, setKey] = useState(""); // a stream key typed here, not saved yet
  const [busy, setBusy] = useState(null); // "save" | "start" | "stop" | "logo" | "youtube" while the server is asked
  const [problem, setProblem] = useState(null); // what the server last refused, and why
  const [choosing, setChoosing] = useState(false); // Save asking: a new layout, or over one there is
  const [fromLayout, setFromLayout] = useState(null); // the saved layout last used or saved here: Save suggests overwriting it
  const [loadError, setLoadError] = useState(null);

  const draftOrSaved = draft || page?.settings;
  const inGrid = (draftOrSaved?.cells || []).filter((x) => x?.camera).map((x) => x.camera);
  const progress = usePrintProgress(draftOrSaved?.showStatus ? [...new Set(inGrid.map(printerOf))] : []);

  useEffect(() => {
    let live = true;
    const ask = () =>
      !document.hidden &&
      getStream()
        .then((p) => live && (setPage(p), setLoadError(null)))
        .catch((e) => live && setLoadError(errorText(e)));
    ask();
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
  // everything on the page that's saved with Save (a blank number box is sent as it is, for the server to say why not)
  const sendAll = () =>
    saveStream({
      destination: shown.destination, cols: shown.cols, rows: shown.rows, cells: shown.cells, showStatus: shown.showStatus, layout: shown.layout,
      resolution: shown.resolution, secondsAll: shown.secondsAll === "" ? -1 : shown.secondsAll, secondsEach: shown.secondsEach === "" ? -1 : shown.secondsEach,
      borderColor: shown.borderColor, background: shown.background, title: shown.title, description: shown.description, streamKey: key.trim(),
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

  return (
    <div data-testid="stream-section" style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(340px, 2fr)", gap: 20, alignItems: "start" }}>
      {/* left: what the stream looks like; right: going live and what goes into it */}
      <div style={{ minWidth: 0, position: "sticky", top: 0 }}>
        <StreamPreview
          shown={shown} change={change} squares={squares} showStatus={shown.showStatus} live={status.live} resolutions={page.resolutions}
          cameras={cameras} media={page.media} fonts={page.fonts} label={label}
          ask={ask} busy={busy} onSave={saveNow} dirty={changed}
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
                ? status.error ? "Reconnecting…" : `Live on ${destLabel(status.destination)} since ${timeOf(status.startedAt)}`
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

        <SquaresPanel shown={shown} change={change} cameras={cameras} finding={finding && !cameras.length} />
        <LayoutPanel shown={shown} count={inGrid.length} change={change} />
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
  );
}
