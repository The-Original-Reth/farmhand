import { useEffect, useState } from "react";
import { c } from "../theme.js";
import { cancelButton, primaryButton, uiText } from "../styles.js";
import {
  errorText, getStreamControl, getStreamPlugins, renameSlideshow, saveStreamDesign, saveStreamLayouts, scanStreamFolder,
  chooseStreamPlugins, copyStreamLayout, startAllStreams, startStreamPlugin, stopAllStreams, stopStreamPlugin,
} from "../api.js";
import { useData } from "../data.jsx";
import { usePhone } from "../hooks/useMediaQuery.js";
import { usePrintProgress, usePrinterCameras } from "../monitor/cameras.js";
import { StreamPreview } from "./StreamPreview.jsx";
import { cameraOf, followCameras, printerOf } from "./shapes.js";
import { MuteSwitch, WordsPanel } from "./StreamPanels.jsx";
import { DefaultsPanel } from "./StreamSquares.jsx";
import { MusicPanel } from "./MusicPanel.jsx";
import { MusicFolders } from "./MusicFolders.jsx";
import { HoldingScreenPanel } from "./HoldingScreen.jsx";
import { SaveChoice, SavedLayoutsPanel, sameAs, shownOf } from "./SavedLayouts.jsx";
import { StreamsPanel } from "./StreamsPanel.jsx";
import { SchedulePanel } from "./SchedulePanel.jsx";

// Stream control, the plugin built into Farmhand: one stream designed here, sent to YouTube and Twitch by their stream
// plugins. Left: the stream as it will look (StreamPreview, the stream plugins' own editor: drag squares about, click
// one to change it). Right: the stream plugins with Go live and Stop (each, or all at once), what the sites are told,
// the holding screen, the defaults, the music, saved layouts, Save, and the schedule. A camera is named as on Monitor
// ("printer id:camera name"). Saving changes the stream as it goes out: each plugin following it picks it up.
const STREAMS_EVERY_MS = 5000;
// Mute and Autoplay music, kept in this browser (a browser that keeps nothing: off, and kept for this visit only)
const MUTE_KEY = "farmhand-stream-control-music-muted";
const AUTOPLAY_KEY = "farmhand-stream-control-music-autoplay";
const storedOn = (key) => {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
};
const store = (key, on) => {
  try {
    localStorage.setItem(key, on ? "1" : "0");
  } catch {
    // (kept for this visit only)
  }
};

export function StreamControlSection({ onOpenPlugin, onOpenPlugins }) {
  const { printers } = useData();
  const phone = usePhone();
  const active = printers.filter((p) => !p.decommissioned);
  const { cams } = usePrinterCameras(active);
  const [page, setPage] = useState(null); // what the server says (getStreamControl)
  const [draft, setDraft] = useState(null); // the design as changed here, not saved yet (null = as saved)
  const [busy, setBusy] = useState(null); // what's being asked: "save", "picture", "start:<id>", "start-all"...
  const [problem, setProblem] = useState(null);
  const [choosing, setChoosing] = useState(false); // Save asking: a new layout, or over one there is
  const [fromLayout, setFromLayout] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [muted, setMuted] = useState(() => storedOn(MUTE_KEY)); // Mute: the music silent on this page only (the streams keep it)
  const mute = (on) => (setMuted(on), store(MUTE_KEY, on));
  // Autoplay music: this page plays the stream's music by itself while it's open, round and round (as the stream does)
  const [autoplay, setAutoplay] = useState(() => storedOn(AUTOPLAY_KEY));
  const turnAutoplay = (on) => (setAutoplay(on), store(AUTOPLAY_KEY, on));
  const [musicWaits, setMusicWaits] = useState(false); // the browser holds the music back until the page is clicked

  const draftOrSaved = draft || page?.design;
  const inGrid = (draftOrSaved?.cells || []).filter((x) => x?.camera).map((x) => x.camera);
  const progress = usePrintProgress(draftOrSaved?.showStatus ? [...new Set(inGrid.map(printerOf))] : []);

  // a page from the server: one answered without the stream plugins keeps those last heard
  const take = (p) => setPage((now) => ({ ...p, streams: p.streams ?? now?.streams ?? [], happened: p.happened ?? now?.happened ?? [] }));

  useEffect(() => {
    let live = true;
    getStreamControl().then((p) => live && (take(p), setLoadError(null))).catch((e) => live && setLoadError(errorText(e)));
    const timer = setInterval(() => {
      if (document.hidden) return;
      getStreamPlugins()
        .then((r) => live && setPage((now) => now && { ...now, streams: r.streams, happened: r.happened }))
        .catch(() => {});
    }, STREAMS_EVERY_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  if (!page) {
    return <div style={uiText(13, loadError ? c.danger : c.textFaint)}>{loadError ? `Couldn't load Stream control: ${loadError}` : "Loading…"}</div>;
  }

  const saved = page.design;
  const shown = followCameras(draft || saved, cams);
  const changed = !!draft && Object.keys(draft).some((k) => JSON.stringify(draft[k]) !== JSON.stringify(saved[k]));
  const change = (what) => {
    setDraft({ ...shown, ...what });
    setProblem(null);
  };

  const label = (k) => {
    const id = printerOf(k);
    const p = printers.find((x) => x.id === id);
    const many = (cams[id]?.webcams || []).length > 1;
    return p ? (many ? `${p.name} · ${cameraOf(k)}` : p.name) : `Printer ${id} · ${cameraOf(k)}`;
  };
  const cameras = active.flatMap((p) => (cams[p.id]?.webcams || []).map((cam) => ({ key: `${p.id}:${cam.name}` }))).map((x) => ({ ...x, label: label(x.key) }));
  const finding = active.some((p) => !cams[p.id] || cams[p.id].kept);

  // ask the server (busy as `what`); the page it answers is taken. The page, or null when it couldn't.
  const ask = async (what, call) => {
    setBusy(what);
    setProblem(null);
    try {
      const p = await call();
      take(p);
      return p;
    } catch (e) {
      setProblem(errorText(e));
      return null;
    } finally {
      setBusy(null);
    }
  };
  const renameShow = async (old, name) => {
    const p = await ask("picture", () => renameSlideshow(old, name));
    if (!p) return null;
    setDraft((d) => d && { ...d, cells: d.cells.map((x) => (x && !x.camera && x.slideshow === old ? { ...x, slideshow: name } : x)) });
    return p;
  };
  // everything Save saves (a blank number box is sent as it is, for the server to say why not)
  const sendAll = () =>
    saveStreamDesign({
      cols: shown.cols, rows: shown.rows, cells: shown.cells, showStatus: shown.showStatus, layout: shown.layout, resolution: shown.resolution,
      secondsAll: shown.secondsAll === "" ? -1 : shown.secondsAll, secondsEach: shown.secondsEach === "" ? -1 : shown.secondsEach,
      borderColor: shown.borderColor, background: shown.background, font: shown.font, color: shown.color,
      music: shown.music, musicVolume: shown.musicVolume, musicShuffle: shown.musicShuffle, musicFrom: shown.musicFrom, delay: shown.delay === "" ? -1 : shown.delay,
      holding: shown.holding, title: shown.title, description: shown.description,
    });
  const saveAll = async () => {
    const p = await ask("save", sendAll);
    if (p) setDraft(null);
    return p;
  };
  const discard = () => (setDraft(null), setProblem(null));
  const saveLayouts = async (list) => {
    const layouts = await saveStreamLayouts(list);
    setPage((now) => ({ ...now, layouts }));
    return layouts;
  };
  const saveWithLayout = async ({ name, list }) => {
    if (!(await saveAll())) return false;
    try {
      await saveLayouts(list);
    } catch (e) {
      setProblem(`The stream was saved, but not the layout: ${errorText(e)}`);
      return false;
    }
    setFromLayout(name);
    setChoosing(false);
    return true;
  };
  // Save just `fields`: anything else changed here and not saved yet stays so
  const savePart = async (what, fields) => {
    const p = await ask(what, () => saveStreamDesign(fields));
    if (p && draft) {
      const next = { ...shown };
      for (const k of Object.keys(fields)) next[k] = p.design[k] ?? fields[k];
      const now = followCameras(p.design, cams);
      const same = Object.keys(now).every((k) => JSON.stringify(now[k]) === JSON.stringify(next[k]));
      setDraft(same ? null : next);
    }
    return p;
  };
  const saveHolding = () => savePart("holding", { holding: shown.holding });
  const switchTo = async (l) => {
    if (!(await savePart("save", shownOf(l)))) return false;
    setFromLayout(l.name);
    return true;
  };

  // Copy layout: a stream's own layout made Stream control's (anything changed here and not saved yet is let go).
  // { copied, problems } once done, or null when it couldn't.
  const copyLayout = async (id) => {
    setBusy("copy");
    setProblem(null);
    try {
      const r = await copyStreamLayout(id);
      take(r.page);
      setDraft(null);
      return { copied: r.copied, problems: r.problems };
    } catch (e) {
      setProblem(errorText(e));
      return null;
    } finally {
      setBusy(null);
    }
  };

  // Which stream plugins are brought in (saved straight away, on its own)
  const choose = async (ids) => {
    setBusy("choose");
    setProblem(null);
    try {
      const r = await chooseStreamPlugins(ids);
      setPage((now) => ({ ...now, streams: r.streams, happened: r.happened }));
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  // Go live and Stop: one stream plugin, or all of them. What's changed here is saved first, so it goes out.
  const streamAnswer = (answers) =>
    setPage((now) => ({ ...now, streams: now.streams.map((s) => answers.find((a) => a.id === s.id) || s) }));
  const act = async (what, call, saveFirst) => {
    if (saveFirst && changed && !(await saveAll())) return;
    setBusy(what);
    setProblem(null);
    try {
      const got = await call();
      const answers = Array.isArray(got) ? got : [got];
      streamAnswer(answers);
      const failed = answers.filter((a) => a.error && !a.live && what.startsWith("start"));
      if (failed.length) setProblem(failed.map((a) => `${a.site}: ${a.error}`).join(" "));
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  const squares = shown.cells.map((cell) => {
    if (cell?.camera) {
      const id = printerOf(cell.camera);
      const cam = (cams[id]?.webcams || []).find((x) => x.name === cameraOf(cell.camera)) || null;
      return { type: "camera", key: cell.camera, label: label(cell.camera), cam, print: progress[id] || null, background: cell.background || null, cell };
    }
    return cell ? { type: "card", cell } : null;
  });
  const anyLive = page.streams.some((s) => s.live);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
    {/* at the top, as on the stream plugins' own pages: Mute, for the music on this page */}
    <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
      <MuteSwitch muted={muted} onMute={mute} />
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 6, cursor: "pointer" })}
        title="Play the stream's music on this page by itself while it's open (Mute silences it)">
        <input type="checkbox" data-testid="stream-control-autoplay" checked={autoplay} onChange={(e) => turnAutoplay(e.target.checked)} />
        Autoplay music
      </label>
      {autoplay && musicWaits && (
        <span data-testid="stream-control-music-waiting" style={uiText(12, c.amber)}
          title="Browsers only play a page's sound once it has been clicked. To have it start straight away, allow sound or autoplay for this address in the browser's site settings.">
          ♪ The music starts with your first click on the page
        </span>
      )}
    </div>
    <div data-testid="stream-control" style={{ display: "grid", gridTemplateColumns: phone ? "minmax(0, 1fr)" : "minmax(0, 3fr) minmax(340px, 2fr)", gap: phone ? 16 : 20, alignItems: "start" }}>
      <div style={{ minWidth: 0, ...(!phone && { position: "sticky", top: 0 }) }}>
        <StreamPreview
          shown={shown} change={change} squares={squares} showStatus={shown.showStatus} live={false} resolutions={page.resolutions}
          cameras={cameras} media={page.media} fonts={page.fonts} label={label}
          ask={ask} busy={busy} onSave={saveAll} dirty={changed} onRenameSlideshow={renameShow} onRevert={discard}
          onResync={() => ask("resync", scanStreamFolder)}
          cycle={shown.layout === "cycle" ? { all: Number(shown.secondsAll) || 0, each: Math.max(1, Number(shown.secondsEach) || 0) } : null}
        />
      </div>
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
        <StreamsPanel
          streams={page.streams} busy={busy} happened={page.happened} onOpenPlugin={onOpenPlugin} onOpenPlugins={onOpenPlugins}
          onStart={(id) => act(`start:${id}`, () => startStreamPlugin(id), true)}
          onStop={(id) => act(`stop:${id}`, () => stopStreamPlugin(id), false)}
          onAll={(action) => act(`${action}-all`, action === "start" ? startAllStreams : stopAllStreams, action === "start")}
          onChoose={(ids) => choose(ids)}
          onCopy={copyLayout}
        />
        {problem && (
          <div data-testid="stream-control-problem" style={uiText(13, c.danger, { lineHeight: 1.5 })}>
            {problem}
          </div>
        )}
        <WordsPanel shown={shown} change={change} />
        <HoldingScreenPanel shown={shown} change={change} media={page.media} fonts={page.fonts} saved={saved.holding} onSave={saveHolding} busy={busy} />
        <DefaultsPanel shown={shown} change={change} cameras={cameras} finding={finding && !cameras.length} count={inGrid.length} fonts={page.fonts} />
        <MusicPanel
          shown={shown} change={change} media={page.media} ask={ask} busy={busy} live={false} enabled={autoplay} onWaiting={setMusicWaits} savedVolume={saved.musicVolume} muted={muted}
          sourceOf={(name) => {
            const from = page.media.musicTracks.find((t) => t.name === name)?.source;
            return page.media.musicSources.find((s) => s.id === from)?.label.replace("'s music folder", "'s") || "";
          }}
          extra={<MusicFolders sources={page.media.musicSources} chosen={saved.musicFrom} busy={busy} onChoose={(ids) => savePart("music", { musicFrom: ids })} />}
        />
        <SavedLayoutsPanel layouts={page.layouts} onSave={saveLayouts} saved={saved} label={label} switchTo={switchTo} />
        {/* Save: under the saved layouts, as on the stream plugins' own pages */}
        <SaveRow
          changed={changed} anyLive={anyLive} busy={busy} choosing={choosing} layouts={page.layouts} shown={shown} saved={saved}
          fromLayout={fromLayout} onDiscard={discard} onChoose={() => (setChoosing(true), setProblem(null))} onCancel={() => setChoosing(false)}
          onConfirm={saveWithLayout}
        />
        <SchedulePanel schedule={page.schedule} streams={page.streams.filter((s) => s.chosen)} timeZone={page.timeZone} onSaved={take} />
      </div>
    </div>
    </div>
  );
}

// Save (as a layout too: a new one, or over one there is), and whether there's anything to save
function SaveRow({ changed, anyLive, busy, choosing, layouts, shown, saved, fromLayout, onDiscard, onChoose, onCancel, onConfirm }) {
  if (choosing) {
    return (
      <SaveChoice
        layouts={layouts} shown={shown} busy={busy === "save"} onConfirm={onConfirm} onCancel={onCancel}
        suggested={fromLayout || layouts.find((l) => sameAs(l, saved))?.name}
      />
    );
  }
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={uiText(12, changed ? c.amber : c.textFaint, { flex: 1 })}>
        {changed
          ? anyLive ? "Not saved yet. Saving changes the stream as it goes out, on every site." : "Not saved yet."
          : "Saved. Save again to keep this as a layout."}
      </div>
      {changed && (
        <button type="button" onClick={onDiscard} disabled={!!busy} style={cancelButton(!!busy)}>
          Discard
        </button>
      )}
      <button type="button" data-testid="stream-control-save" onClick={onChoose} disabled={!!busy} style={primaryButton(!!busy)}>
        Save
      </button>
    </div>
  );
}
