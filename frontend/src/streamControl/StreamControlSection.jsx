import { useState } from "react";
import { c } from "../theme.js";
import { uiText } from "../styles.js";
import {
  errorText, reconnectNas, renameSlideshow, saveStreamDesign, saveStreamLayouts, scanStreamFolder,
  chooseStreamPlugins, controlStreamMusic, copyStreamLayout, startAllStreams, startStreamPlugin, stopAllStreams, stopStreamPlugin,
} from "../api.js";
import { useData } from "../data.jsx";
import { usePhone } from "../hooks/useMediaQuery.js";
import { usePrintProgress, usePrinterCameras } from "../monitor/cameras.js";
import { StreamPreview } from "./StreamPreview.jsx";
import { cameraOf, followCameras, printerOf, wordsShown } from "./shapes.js";
import { MuteSwitch, WordsPanel } from "./StreamPanels.jsx";
import { DefaultsPanel } from "./StreamSquares.jsx";
import { MusicPanel } from "./MusicPanel.jsx";
import { MusicFolders } from "./MusicFolders.jsx";
import { HoldingScreenPanel } from "./HoldingScreen.jsx";
import { SaveRow, SavedLayoutsPanel, shownOf } from "./SavedLayouts.jsx";
import { StreamsPanel } from "./StreamsPanel.jsx";
import { SchedulePanel } from "./SchedulePanel.jsx";
import { useStoredSwitch, useStreamControlPage } from "./useStreamControl.js";

// Stream control, the plugin built into Farmhand: one stream designed here, sent to YouTube and Twitch by their stream
// plugins. Left: the stream as it will look (StreamPreview, the stream plugins' own editor: drag squares about, click
// one to change it). Right: the stream plugins with Go live and Stop (each, or all at once), what the sites are told,
// the holding screen, the defaults, the music, saved layouts, Save, and the schedule. A camera is named as on Monitor
// ("printer id:camera name"). Saving changes the stream as it goes out: each plugin following it picks it up.
export function StreamControlSection({ onOpenPlugin, onOpenPlugins }) {
  const { printers } = useData();
  const phone = usePhone();
  const active = printers.filter((p) => !p.decommissioned);
  const { cams } = usePrinterCameras(active);
  const { page, loadError, take, setPage } = useStreamControlPage();
  const [draft, setDraft] = useState(null); // the design as changed here, not saved yet (null = as saved)
  const [busy, setBusy] = useState(null); // what's being asked: "save", "picture", "start:<id>", "start-all"...
  const [problem, setProblem] = useState(null);
  const [choosing, setChoosing] = useState(false); // Save asking: a new layout, or over one there is
  const [fromLayout, setFromLayout] = useState(null);
  // Mute: the music silent on this page only (the streams keep it). Autoplay music: this page plays the stream's music
  // by itself while it's open. Both kept in this browser.
  const [muted, mute] = useStoredSwitch("farmhand-stream-control-music-muted");
  const [autoplay, turnAutoplay] = useStoredSwitch("farmhand-stream-control-music-autoplay");
  const [musicWaits, setMusicWaits] = useState(false); // the browser holds the music back until the page is clicked

  const draftOrSaved = draft || page?.design;
  const inGrid = (draftOrSaved?.cells || []).filter((x) => x?.camera).map((x) => x.camera);
  // the prints of the printers whose cameras have their name and print written on them
  const worded = (draftOrSaved?.cells || []).filter((x) => x?.camera && wordsShown(x, draftOrSaved.showStatus)).map((x) => x.camera);
  const progress = usePrintProgress([...new Set(worded.map(printerOf))]);

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

  // ask the server (busy as `what`): what `work` answers, or null when it couldn't (and the problem is shown)
  const run = async (what, work) => {
    setBusy(what);
    setProblem(null);
    try {
      return await work();
    } catch (e) {
      setProblem(errorText(e));
      return null;
    } finally {
      setBusy(null);
    }
  };
  // ask the server for a change; the page it answers is taken. The page, or null when it couldn't.
  const ask = (what, call) =>
    run(what, async () => {
      const p = await call();
      take(p);
      return p;
    });
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
  const copyLayout = (id) =>
    run("copy", async () => {
      const r = await copyStreamLayout(id);
      take(r.page);
      setDraft(null);
      return { copied: r.copied, problems: r.problems };
    });

  // Which stream plugins are brought in (saved straight away, on its own)
  const choose = (ids) =>
    run("choose", async () => {
      const r = await chooseStreamPlugins(ids);
      setPage((now) => ({ ...now, streams: r.streams, happened: r.happened }));
    });

  // Go live and Stop: one stream plugin, or all of them. What's changed here is saved first, so it goes out.
  const streamAnswer = (answers) =>
    setPage((now) => ({ ...now, streams: now.streams.map((s) => answers.find((a) => a.id === s.id) || s) }));
  const act = async (what, call, saveFirst) => {
    if (saveFirst && changed && !(await saveAll())) return;
    await run(what, async () => {
      const got = await call();
      const answers = Array.isArray(got) ? got : [got];
      streamAnswer(answers);
      const failed = answers.filter((a) => a.error && !a.live && what.startsWith("start"));
      if (failed.length) setProblem(failed.map((a) => `${a.site}: ${a.error}`).join(" "));
    });
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
  // the music on the streams: while one brought in is live, the music panel's buttons are its (the first one live that
  // says what it plays is shown; each one live is told)
  const liveHere = page.streams.filter((s) => s.enabled && s.chosen && s.live);
  const onAir = liveHere.find((s) => s.music) || null;
  const controlMusic = (action) =>
    run("music", async () => {
      const r = await controlStreamMusic(action);
      setPage((now) => ({ ...now, streams: r.streams, happened: r.happened }));
    });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
    {/* at the top, as on the stream plugins' own pages: Mute, for the music on this page */}
    <MuteSwitch muted={muted} onMute={mute} />
    <div data-testid="stream-control" style={{ display: "grid", gridTemplateColumns: phone ? "minmax(0, 1fr)" : "minmax(0, 3fr) minmax(340px, 2fr)", gap: phone ? 16 : 20, alignItems: "start" }}>
      <div style={{ minWidth: 0, ...(!phone && { position: "sticky", top: 0 }) }}>
        <StreamPreview
          shown={shown} change={change} squares={squares} showStatus={shown.showStatus} resolutions={page.resolutions}
          cameras={cameras} media={page.media} fonts={page.fonts} label={label}
          ask={ask} busy={busy} onSave={saveAll} dirty={changed} onRenameSlideshow={renameShow} onRevert={discard}
          onResync={() => ask("resync", scanStreamFolder)} onReconnect={() => ask("reconnect", reconnectNas)}
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
          media={page.media} onReconnect={() => ask("reconnect", reconnectNas)}
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
          shown={shown} change={change} media={page.media} ask={ask} busy={busy} autoplay={autoplay} onWaiting={setMusicWaits} muted={muted}
          live={liveHere.length > 0} onAir={onAir?.music ?? null} heardAt={onAir?.heardAt ?? 0} onControl={controlMusic}
          sourceOf={(name) => {
            const from = page.media.musicTracks.find((t) => t.name === name)?.source;
            return page.media.musicSources.find((s) => s.id === from)?.label.replace("'s music folder", "'s") || "";
          }}
          extra={
            <>
              {/* Autoplay music: this page plays the music by itself while it's open (kept in this browser) */}
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6, cursor: "pointer" })}
                  title="Play the stream's music on this page by itself while it's open (Mute, at the top of the page, silences it)">
                  <input type="checkbox" data-testid="stream-control-autoplay" checked={autoplay} onChange={(e) => turnAutoplay(e.target.checked)} />
                  Autoplay music on this page
                </label>
                {autoplay && musicWaits && (
                  <span data-testid="stream-control-music-waiting" style={uiText(12, c.amber)}
                    title="Browsers only play a page's sound once it has been clicked. To have it start straight away, allow sound or autoplay for this address in the browser's site settings.">
                    ♪ The music starts with your first click on the page
                  </span>
                )}
              </div>
              <MusicFolders sources={page.media.musicSources} chosen={saved.musicFrom} busy={busy} onChoose={(ids) => savePart("music", { musicFrom: ids })} />
            </>
          }
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
