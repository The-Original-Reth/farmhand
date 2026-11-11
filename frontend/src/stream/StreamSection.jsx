import { useEffect, useRef, useState } from "react";
import { c } from "../theme.js";
import { cancelButton, primaryButton, uiText } from "../styles.js";
import { errorText, getStream, renameSlideshow, saveStream, scanStreamFolder, startStream, stopStream } from "../api.js";
import { useData } from "../data.jsx";
import { usePrintProgress, usePrinterCameras } from "../monitor/cameras.js";
import { StreamPreview } from "./StreamPreview.jsx";
import { cameraOf, printerOf } from "./shapes.js";
import { LiveStatusPanel, MuteSwitch, StreamSwitch, WhereToPanel } from "./StreamPanels.jsx";
import { DefaultsPanel } from "./StreamSquares.jsx";
import { STREAM_CHANNEL, YouTubeSettingsButton, openYouTubeSettings } from "./YouTubeSettings.jsx";
import { MusicPanel } from "./MusicPanel.jsx";
import { SaveChoice, SavedLayoutsPanel, sameAs, shownOf } from "./SavedLayouts.jsx";

// The Stream page: Farmhand sends the printers' cameras live to YouTube itself, laid out in a grid of
// squares (each a camera, a logo or nothing, with a border round it) or taking turns, with each printer's name and print
// written under its camera. No OBS needed. Everything YouTube (the broadcast's title, tags and privacy, the stream key,
// the account) is in the YouTube settings window (YouTubeSettings.jsx), which saves on its own; this page's Save never
// sends those. Cameras are found as on Monitor (cameras.js) and named the same way ("printer id:camera
// name").
const STATUS_EVERY_MS = 5000;
const MUTE_KEY = "farmhand-stream-music-muted"; // Mute, kept in this browser
const mutedAtFirst = () => {
  try {
    return localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false; // (a browser that keeps nothing: not muted)
  }
};

export function StreamSection({ layouts = [], onSaveLayouts, onSlideshowRenamed }) {
  const { printers } = useData();
  const active = printers.filter((p) => !p.decommissioned);
  const music = useRef(null); // the music panel's own start and stop, for the switch (MusicPanel `control`)
  const [resynced, setResynced] = useState(false); // Resync pressed since the last change: the preview keeps the server's time, changes or not
  const [muted, setMuted] = useState(mutedAtFirst); // Mute: the music silent on this page only (the stream keeps it)
  const mute = (on) => {
    setMuted(on);
    try {
      localStorage.setItem(MUTE_KEY, on ? "1" : "0");
    } catch {
      // (kept for this visit only)
    }
  };
  const [musicWaits, setMusicWaits] = useState(false); // the browser holds the music back until the page is clicked
  const [page, setPage] = useState(null); // what the server says: { settings, status, destinations, resolutions, fonts, media, youtube }
  const enabled = page?.settings.enabled !== false; // the switch: off, nothing streams (the page works as ever)
  const { cams } = usePrinterCameras(active);
  const [draft, setDraft] = useState(null); // the choices as changed here, not saved yet (null = as saved)
  const [busy, setBusy] = useState(null); // "save" | "start" | "stop" | "logo" | "youtube" while the server is asked
  const [problem, setProblem] = useState(null); // what the server last refused, and why
  const [choosing, setChoosing] = useState(false); // Save asking: a new layout, or over one there is
  const [fromLayout, setFromLayout] = useState(null); // the saved layout last used or saved here: Save suggests overwriting it
  const [loadError, setLoadError] = useState(null);

  const draftOrSaved = draft || page?.settings;
  const inGrid = (draftOrSaved?.cells || []).filter((x) => x?.camera).map((x) => x.camera);
  const progress = usePrintProgress(draftOrSaved?.showStatus ? [...new Set(inGrid.map(printerOf))] : [], { keepErrors: true });

  useEffect(() => {
    let live = true;
    const ask = (first) =>
      (first === true || !document.hidden) &&
      getStream()
        .then((p) => live && (setPage(p), setLoadError(null)))
        .catch((e) => live && setLoadError(errorText(e)));
    ask(true);
    const timer = setInterval(ask, STATUS_EVERY_MS);
    // the YouTube settings window saved: shown straight away (squares and the rest changed here and not saved stay so)
    let heard = null;
    try {
      heard = new BroadcastChannel(STREAM_CHANNEL);
      heard.onmessage = () =>
        getStream().then((p) => {
          if (!live) return;
          setPage(p);
          setDraft((d) => d && { ...d, title: p.settings.title, description: p.settings.description, youtube: p.settings.youtube });
        }).catch(() => {});
    } catch {
      // (an old browser: the next look catches up)
    }
    return () => {
      live = false;
      clearInterval(timer);
      heard?.close();
    };
  }, []);

  if (!page) {
    return <div style={uiText(13, loadError ? c.danger : c.textFaint)}>{loadError ? `Couldn't load the stream: ${loadError}` : "Loading…"}</div>;
  }

  const saved = page.settings;
  const shown = draft || saved;
  // (the switch is saved on its own, as soon as it is turned, so it never counts as a change still to save)
  const differs = !!draft && Object.keys(draft).some((k) => k !== "enabled" && JSON.stringify(draft[k]) !== JSON.stringify(saved[k]));
  const changed = differs;
  const change = (what) => {
    setResynced(false); // (changed again: the preview no longer matches what the server has)
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
      borderColor: shown.borderColor, background: shown.background, font: shown.font, color: shown.color,
      music: shown.music, musicVolume: shown.musicVolume, musicShuffle: shown.musicShuffle, delay: shown.delay === "" ? -1 : shown.delay,
    });
  // Save everything on the page: once saved, nothing here is still to be saved. The page as the server answered, or null.
  const saveAll = async () => {
    const p = await ask("save", sendAll);
    if (p) forget();
    return p;
  };
  const forget = () => setDraft(null);
  const discard = () => (forget(), setProblem(null));
  // Resync: the server read again (its stream folder too: pictures, slideshows, tracks) and the preview's slideshows
  // and taking turns back on its time of day, keeping what's changed here and not saved yet
  const resync = async () => {
    if (await ask("resync", scanStreamFolder)) setResynced(true);
  };
  // Save: the stream's settings, and the layout under the name chosen (a new one, or over one there is)
  const saveWithLayout = async ({ name, list }) => {
    if (!(await saveAll())) return false;
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
  // The switch at the top. Off: ffmpeg on the server stops and going live waits until it's on again; everything else on
  // the page works as ever (what's changed here and not saved yet stays so).
  // (turned on, the music starts within the click itself: browsers only let a page start sound straight from a click)
  const turn = async (on) => {
    if (on) music.current?.start();
    const p = await ask("switch", () => saveStream({ enabled: on }));
    if (on && !p) music.current?.stop(); // it stayed off
  };
  // Go live: what's changed here is saved first
  const start = async () => {
    if (changed && !(await saveAll())) return;
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

  const head = (
    <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
      <StreamSwitch on={enabled} onTurn={turn} busy={!!busy} />
      <MuteSwitch muted={muted} onMute={mute} />
      {musicWaits && enabled && (
        <button
          type="button" data-testid="stream-music-waiting" style={{ ...cancelButton(false), color: c.amber, borderColor: c.amber }}
          title="Browsers only play a page's sound once it has been clicked. To have it start straight away, allow sound or autoplay for this address in the browser's site settings."
        >
          ♪ The music starts with your first click on the page
        </button>
      )}
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
    {head}
    <div data-testid="stream-section" style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(340px, 2fr)", gap: 20, alignItems: "start" }}>
      {/* left: what the stream looks like; right: going live and what goes into it */}
      <div style={{ minWidth: 0, position: "sticky", top: 0 }}>
        <StreamPreview
          shown={shown} change={change} squares={squares} showStatus={shown.showStatus} live={status.live} liveResolution={status.resolution} resolutions={page.resolutions}
          cameras={cameras} media={page.media} fonts={page.fonts} label={label}
          ask={ask} busy={busy} onSave={saveAll} dirty={changed} onRenameSlideshow={renameShow} onRevert={discard} still={!enabled} onResync={resync} resynced={resynced && changed}
          serverClock={status.serverTime !== null && (!changed || resynced) ? { serverTime: status.serverTime, heardAt: status.heardAt, live: status.onAir } : null}
          cycle={shown.layout === "cycle" ? { all: Number(shown.secondsAll) || 0, each: Math.max(1, Number(shown.secondsEach) || 0) } : null}
        />
      </div>
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
        <LiveStatusPanel status={status} destLabel={destLabel} destination={shown.destination} busy={busy} onStart={start} onStop={stop} off={!enabled} />
        {problem && (
          <div data-testid="stream-problem" style={uiText(13, c.danger, { lineHeight: 1.5 })}>
            {problem}
          </div>
        )}

        <WhereToPanel
          destination={shown.destination} destinations={page.destinations} onDestination={(destination) => change({ destination })}
          delay={shown.delay} onDelay={(v) => change({ delay: v })} live={status.live}
          youtubeSettings={
            <>
              <YouTubeSettingsButton shown={saved} youtube={page.youtube} keySet={saved.keySet} onOpen={openYouTubeSettings} />
              {status.title && (
                <div data-testid="stream-title-status" style={uiText(12, status.title.state === "failed" ? c.danger : status.title.state === "done" ? c.green : c.amber, { lineHeight: 1.5 })}>
                  {status.title.message}
                </div>
              )}
            </>
          }
        />

        <DefaultsPanel shown={shown} change={change} cameras={cameras} finding={finding && !cameras.length} count={inGrid.length} fonts={page.fonts} />
        <MusicPanel shown={shown} change={change} media={page.media} ask={ask} busy={busy} live={status.live} onAir={status.music} heardAt={status.heardAt} enabled={enabled} control={music} onWaiting={setMusicWaits} muted={muted} />
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
              <button type="button" onClick={discard} disabled={!!busy} style={cancelButton(!!busy)}>
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
