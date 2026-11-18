// Stream control, the plugin built into Farmhand (/stream-control), in the real API's shapes
// (backend/app/routers/stream_control.py, services/stream_control/). Its on/off switch is on /plugins (routes/plugins.js:
// farm.streamControl.enabled). The design is checked only roughly here (the real one says why it won't take something);
// the stream folder keeps file names only, and its pictures are drawn as stand-ins. The stream plugins are the pretend
// YouTube and Twitch ones: they "go live" when told to, and Twitch has no stream key until it's been refused once.
import { HttpError } from "../core.js";

const FONTS = [
  ["dejavu-sans", "DejaVu Sans", "sans-serif"], ["play", "Play (Farmhand's own)", "sans-serif"], ["play-bold", "Play Bold", "sans-serif"],
  ["liberation-serif", "Liberation Serif (like Times New Roman)", "serif"], ["roboto", "Roboto", "sans-serif"], ["bebas-neue", "Bebas Neue (capitals)", "sans-serif"],
  ["comic-neue", "Comic Neue", "cursive"], ["fira-code", "Fira Code", "monospace"],
].map(([key, label, generic]) => ({ key, label, generic }));
const RESOLUTIONS = [{ key: "720p", label: "720p (1280×720)" }, { key: "1080p", label: "1080p (1920×1080)" }, { key: "1440p", label: "2K (2560×1440)" }];
const SAVED = ["cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "resolution", "border_color", "background", "font",
  "color", "music", "music_volume", "music_shuffle", "music_from", "delay", "holding", "title", "description"];
const HEX = /^#[0-9A-Fa-f]{6}$/;
const TIME = /^([01]\d|2[0-3]):([0-5]\d)$/;
// a stand-in for a picture of the stream folder: its name on a coloured card
const standIn = (name) => ({
  type: "image/svg+xml",
  body: `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="#2A4D69"/><text x="320" y="190" font-family="sans-serif" font-size="28" fill="#fff" text-anchor="middle">${name.replace(/[<&>]/g, "")}</text></svg>`,
});

export function streamControlRoutes(ctx) {
  const { farm, on, requireConfirm, fileRoutes, pluginNeeds } = ctx;
  // (the switch may be set before anything else is: routes/plugins.js)
  const state = () => (farm.streamControl?.design ? farm.streamControl : (farm.streamControl = { ...fresh(), enabled: !!farm.streamControl?.enabled }));
  const fresh = () => ({
    enabled: false,
    design: {
      cols: 2, rows: 1, cells: [{ camera: "1:Bed" }, { background: "#1F3A5F", image: null, slideshow: null, seconds: 10, text: "Printing live", color: null, font: null, band: false,
        picture_box: { x: 0, y: 0, w: 1, h: 1 }, text_box: { x: 0.5, y: 0.5, size: 0.125 }, captions: {}, picture_boxes: {}, layers: [], slide_layers: {} }],
      show_status: true, layout: "grid", seconds_all: 30, seconds_each: 20, resolution: "720p", border_color: "#000000", background: "#000000",
      font: "play", color: "#FFFFFF", music: true, music_volume: 50, music_shuffle: true, delay: 60,
      holding: { text: "Back in a minute", image: null, background: null, color: null, font: null }, title: "The print farm, live", description: "",
      revision: 1, saved_at: new Date().toISOString(),
    },
    layouts: [],
    schedule: { on: false, entries: [] },
    happened: [],
    media: { images: ["logo.png"], slideshows: [{ name: "Finished prints", images: ["frog.jpg", "shark.jpg"] }], music: ["Lo-fi beat.mp3"] },
    live: {}, // plugin id -> live
  });
  const sc = () => {
    if (!state().enabled) throw new HttpError(404, "Stream control is switched off. Switch it on on the Plugins page to use it.");
    return state();
  };
  const cameras = (cells) => cells.filter((c) => c?.camera).map((c) => c.camera);
  const design = () => ({ ...state().design, cameras: cameras(state().design.cells) });
  const media = () => ({ path: "/data/nas/farmhand/stream", windows_path: String.raw`\\192.168.10.5\farmhand\stream`, ...state().media, error: null });
  // the stream plugins: the added plugins whose manifest says they can be started from here
  // (YouTube and Twitch, as they are now, from before Stream control: started and stopped through their own page, sending their own layout)
  const BEFORE = { stream: "YouTube", twitch: "Twitch" };
  const controlOf = (p) => (p.manifest.stream_control ? { site: p.manifest.stream_control.site, legacy: false } : BEFORE[p.id] ? { site: BEFORE[p.id], legacy: true } : null);
  const streamPlugins = () => [...(farm.plugins || [])].filter(controlOf).sort((a, b) => a.name.localeCompare(b.name));
  // the ones brought in (state().chosen: their ids; none chosen yet = all of them)
  const isChosen = (id) => !state().chosen || state().chosen.includes(id);
  // what each pretend plugin's own page shows: its links, and (while live) its cameras, one of them down
  const extras = (p) => {
    const live = p.enabled && !!state().live[p.id];
    const links = p.id === "twitch"
      ? [["Watch", "https://www.twitch.tv/printfarm"], ["Chat", "https://www.twitch.tv/popout/printfarm/chat?popout="],
        ["Stream Manager", "https://dashboard.twitch.tv/u/printfarm/stream-manager"], ["Analytics", "https://dashboard.twitch.tv/u/printfarm/analytics/channel-analytics"]]
      : live ? [["Watch", "https://www.youtube.com/watch?v=mockup"], ["Chat and analytics", "https://studio.youtube.com/video/mockup/livestreaming"]] : [];
    return {
      links: links.map(([label, url]) => ({ label, url, title: "" })),
      cameras: live ? [{ key: "1:Bed", label: "Voron 2.4", state: "live", since: 0 }, { key: "2:Bed", label: "Prusa MK4", state: "down", since: 0 }] : [],
      viewers: live && p.id === "stream" ? 12 : null,
      // (Twitch's still filling, behind its holding screen, so both looks show)
      buffer: live ? (p.id === "twitch" ? { seconds: 60, held: 23.5, filling: true, holding: true } : { seconds: 60, held: 59.2, filling: false, holding: false }) : null,
    };
  };
  const entry = (p, answer = null) => ({
    id: p.id, name: p.name, site: controlOf(p).site || p.name, enabled: p.enabled, needs_update: controlOf(p).legacy, has_page: !!p.manifest.page,
    can_read_design: p.permissions.includes("stream:read"), chosen: isChosen(p.id), ...extras(p),
    settings_page: { stream: "/?view=youtube-settings", twitch: "/?view=twitch-settings" }[p.id] || null,
    ...(answer || (p.enabled
      ? { live: !!state().live[p.id], following: !controlOf(p).legacy, error: null, watch_url: state().live[p.id] ? `https://example.com/${p.id}/live` : null, reachable: true }
      : { live: false, following: null, error: null, watch_url: null, reachable: null })),
  });
  // The music folders: Stream control's own and the pretend plugins' own (played from where they are, never copied)
  const THEIR_MUSIC = { stream: ["Lo-fi beat.mp3", "Synthwave drive.mp3"], twitch: ["Chill loop.mp3"] };
  const musicFrom = () => state().design.music_from || ["stream-control"];
  const musicTracks = () => {
    const out = [];
    for (const src of musicFrom()) {
      for (const name of src === "stream-control" ? state().media.music : THEIR_MUSIC[src] || []) {
        if (!out.some((t) => t.name === name)) out.push({ name, source: src });
      }
    }
    return out;
  };
  const pageMedia = () => {
    const own = media();
    const sources = [{ id: "stream-control", label: "Stream control's music folder", tracks: own.music.length, problem: null },
      ...streamPlugins().filter((p) => p.enabled).map((p) => ({ id: p.id, label: `${controlOf(p).site}'s music folder`, tracks: (THEIR_MUSIC[p.id] || []).length, problem: null }))];
    return {
      ...own, music: musicTracks().map((t) => t.name), own_music: own.music, music_tracks: musicTracks(),
      music_sources: sources.map((s) => ({ ...s, chosen: musicFrom().includes(s.id) })),
    };
  };
  const page = (withStreams = true) => ({
    design: design(), resolutions: RESOLUTIONS, fonts: FONTS, media: pageMedia(), layouts: state().layouts, schedule: state().schedule,
    happened: state().happened, time_zone: farm.config.preferences?.time_zone ?? null,
    ...(withStreams && { streams: streamPlugins().map((p) => entry(p)) }),
  });
  const act = (p, action) => {
    if (!p.enabled) throw new HttpError(422, `${p.name} is switched off. Switch it on on the Plugins page first.`);
    if (action === "start" && p.id === "twitch" && !state().twitchTried) {
      state().twitchTried = true; // (once: the next try works, as if the key had been put in)
      return entry(p, { live: null, following: null, error: "There's no Twitch stream key yet: put it in on the Twitch plugin's own page.", watch_url: null, reachable: true, refused: true });
    }
    state().live[p.id] = action === "start";
    return entry(p);
  };
  const one = (id) => {
    const p = (farm.plugins || []).find((x) => x.id === id);
    if (!p) throw new HttpError(404, "Plugin not found");
    if (!controlOf(p)) throw new HttpError(422, `${p.name} isn't a stream plugin Stream control can start and stop.`);
    if (!isChosen(p.id)) throw new HttpError(422, `${p.name} isn't brought into Stream control. Tick it under Streams first.`);
    return p;
  };
  on("PUT", "/stream-control/streams", (_p, body) => {
    sc();
    const ids = body.chosen;
    if (!Array.isArray(ids) || !ids.every((x) => typeof x === "string")) throw new HttpError(422, "Say which streams to bring in, as a list of the plugins' ids.");
    const unknown = ids.find((x) => !streamPlugins().some((p) => p.id === x));
    if (unknown) throw new HttpError(422, `"${unknown}" isn't a stream plugin added to Farmhand.`);
    state().chosen = [...new Set(ids)];
    return { streams: streamPlugins().map((p) => entry(p)), happened: state().happened };
  });

  on("GET", "/stream-control", () => (sc(), page()));
  on("PUT", "/stream-control", (_p, body) => {
    const s = sc();
    const next = { ...s.design };
    for (const k of SAVED) if (body[k] !== undefined && body[k] !== null) next[k] = body[k];
    if (body.cameras && !body.cells) {
      const cols = Math.min(5, Math.max(1, Math.ceil(Math.sqrt(body.cameras.length))));
      const rows = Math.min(5, Math.max(1, Math.ceil(body.cameras.length / cols)));
      Object.assign(next, { cols, rows, cells: [...body.cameras.map((camera) => ({ camera })), ...Array(cols * rows - body.cameras.length).fill(null)] });
    }
    if (!Array.isArray(next.cells) || next.cells.length !== next.cols * next.rows) throw new HttpError(422, `Say what's in each of the grid's ${next.cols * next.rows} squares.`);
    const cams = cameras(next.cells);
    if (new Set(cams).size !== cams.length) throw new HttpError(422, "A camera can only be in one square.");
    for (const k of ["border_color", "background", "color"]) if (!HEX.test(next[k])) throw new HttpError(422, "Choose the colour with the colour picker (#RRGGBB).");
    if (!Number.isInteger(next.delay) || next.delay < 0 || next.delay > 120) throw new HttpError(422, "The stream's delay has to be from 0 to 120 seconds.");
    for (const [k, least] of [["seconds_all", 0], ["seconds_each", 3]]) {
      if (!Number.isInteger(next[k]) || next[k] < least || next[k] > 3600) throw new HttpError(422, `The time has to be from ${least} to 3600 seconds.`);
    }
    if ((next.title || "").length > 100) throw new HttpError(422, `The stream's title can be up to 100 characters; this one has ${next.title.length}.`);
    for (const k of ["border_color", "background", "color"]) next[k] = next[k].toUpperCase();
    s.design = { ...next, title: (next.title || "").trim(), description: (next.description || "").trim(), revision: s.design.revision + 1, saved_at: new Date().toISOString() };
    return page();
  });

  on("GET", "/stream-control/streams", () => (sc(), { streams: streamPlugins().map((p) => entry(p)), happened: state().happened }));
  // Copy layout: the pretend plugins' own layouts (YouTube's a 2x2 of cameras and its logo, Twitch's a slideshow beside a camera)
  const OWN_LAYOUTS = {
    stream: { cols: 2, rows: 2, title: "Live from the print farm", cells: [{ camera: "1:Bed" }, { camera: "2:Bed" }, { background: "#B3261E", image: "youtube-logo.png", text: "" }, null] },
    twitch: { cols: 2, rows: 1, title: "Printing all day", cells: [{ camera: "1:Bed" }, { slideshow: "Twitch prints", seconds: 8, text: "" }] },
  };
  on("POST", "/stream-control/streams/:id/copy-layout", ({ id }) => {
    const s = sc();
    const p = one(id);
    const own = OWN_LAYOUTS[p.id] || { cols: 1, rows: 1, cells: [null] };
    const cell = (c) => (c && !c.camera ? { background: null, image: null, slideshow: null, seconds: 10, text: "", color: null, font: null, band: false,
      picture_box: { x: 0, y: 0, w: 1, h: 1 }, text_box: { x: 0.5, y: 0.5, size: 0.125 }, captions: {}, picture_boxes: {}, layers: [], slide_layers: {}, ...c } : c);
    s.design = { ...s.design, ...own, cells: own.cells.map(cell), revision: s.design.revision + 1, saved_at: new Date().toISOString() };
    const copied = [];
    if (p.id === "stream" && !s.media.images.includes("youtube-logo.png")) (s.media.images = [...s.media.images, "youtube-logo.png"].sort()), copied.push("the picture “youtube-logo.png”");
    if (p.id === "twitch" && !s.media.slideshows.some((x) => x.name === "Twitch prints")) {
      s.media.slideshows.push({ name: "Twitch prints", images: ["frog.jpg", "shark.jpg"] });
      copied.push("“Twitch prints”: “frog.jpg”", "“Twitch prints”: “shark.jpg”");
    }
    return { ...page(), copied, problems: [`${p.name}'s music tracks weren't copied: add them under Music on this page.`] };
  });
  on("POST", "/stream-control/streams/:id/:action", ({ id, action }) => {
    sc();
    if (!["start", "stop"].includes(action)) throw new HttpError(404, "Not Found");
    return act(one(id), action);
  });
  on("POST", "/stream-control/start-all", () => (sc(), { streams: streamPlugins().filter((p) => p.enabled && isChosen(p.id)).map((p) => act(p, "start")) }));
  on("POST", "/stream-control/stop-all", () => (sc(), { streams: streamPlugins().filter((p) => p.enabled && isChosen(p.id)).map((p) => act(p, "stop")) }));

  on("PUT", "/stream-control/schedule", (_p, body) => {
    const s = sc();
    const entries = (body.entries || []).map((e) => {
      if (!Array.isArray(e.days) || !e.days.length) throw new HttpError(422, "Choose at least one day for each time in the schedule.");
      for (const k of ["start", "stop"]) if (e[k] && !TIME.test(e[k])) throw new HttpError(422, "The time has to be a time of day, like 08:00.");
      if (!e.start && !e.stop) throw new HttpError(422, "Each time in the schedule needs a time to go live, a time to stop, or both.");
      if (e.streams !== "all" && (!Array.isArray(e.streams) || !e.streams.length)) throw new HttpError(422, "Choose which streams each time in the schedule is for, or all of them.");
      return { days: [...new Set(e.days)].sort(), start: e.start || null, stop: e.stop || null, streams: e.streams };
    });
    s.schedule = { on: body.on === true, entries };
    return page(false);
  });
  on("PUT", "/stream-control/layouts", (_p, body) => {
    const s = sc();
    if (!Array.isArray(body)) throw new HttpError(422, "The saved layouts must be a list.");
    s.layouts = body.filter((l) => l && typeof l.name === "string" && l.name.trim()).map((l) => ({ ...l, name: l.name.trim() }));
    return page(false);
  });

  // ------------------------------------------------------------------ the stream folder (names only)
  const m = () => sc().media;
  const show = (name) => m().slideshows.find((x) => x.name === name) || (() => { throw new HttpError(404, "That slideshow isn't there."); })();
  const pictures = (body) => {
    const bad = body.files.find((f) => !/\.(png|jpe?g|webp|svg)$/i.test(f));
    if (bad) throw new HttpError(422, "A picture has to be a PNG, JPEG, WebP or SVG file.");
    return body.files;
  };
  on("POST", "/stream-control/scan", () => (sc(), page(false)));
  on("POST", "/stream-control/pictures", (_p, body) => {
    m().images = [...new Set([...m().images, ...pictures(body)])].sort();
    return [201, page(false)];
  });
  on("DELETE", "/stream-control/pictures/:name", ({ name }, _b, q) => {
    requireConfirm(q);
    m().images = m().images.filter((x) => x !== decodeURIComponent(name));
    return page(false);
  });
  on("POST", "/stream-control/slideshows", (_p, body) => {
    const name = (body.name || "").trim();
    if (!name) throw new HttpError(422, "That isn't a name a slideshow can have.");
    if (m().slideshows.some((x) => x.name.toLowerCase() === name.toLowerCase())) throw new HttpError(422, `There's already a slideshow called “${name}”.`);
    m().slideshows.push({ name, images: [] });
    return [201, page(false)];
  });
  on("PUT", "/stream-control/slideshows/:name", ({ name }, body) => {
    const s = show(decodeURIComponent(name));
    const old = s.name;
    s.name = (body.name || "").trim() || old;
    const follow = (cells) => cells.forEach((c) => c && !c.camera && c.slideshow === old && (c.slideshow = s.name));
    follow(state().design.cells);
    state().layouts.forEach((l) => follow(l.cells));
    return page(false);
  });
  on("DELETE", "/stream-control/slideshows/:name", ({ name }, _b, q) => {
    requireConfirm(q);
    show(decodeURIComponent(name));
    m().slideshows = m().slideshows.filter((x) => x.name !== decodeURIComponent(name));
    return page(false);
  });
  on("POST", "/stream-control/slideshows/:name/pictures", ({ name }, body) => {
    const s = show(decodeURIComponent(name));
    s.images = [...new Set([...s.images, ...pictures(body)])];
    return [201, page(false)];
  });
  on("POST", "/stream-control/slideshows/:name/blanks", ({ name }) => {
    const s = show(decodeURIComponent(name));
    const n = Math.max(0, ...s.images.filter((x) => x.startsWith("blank:")).map((x) => Number(x.slice(6)))) + 1;
    s.images.push(`blank:${n}`);
    return [201, page(false)];
  });
  on("PUT", "/stream-control/slideshows/:name/order", ({ name }, body) => {
    const s = show(decodeURIComponent(name));
    s.images = [...new Set([...body.order, ...s.images])].filter((x) => s.images.includes(x));
    return page(false);
  });
  on("DELETE", "/stream-control/slideshows/:name/pictures/:picture", ({ name, picture }, _b, q) => {
    requireConfirm(q);
    const s = show(decodeURIComponent(name));
    s.images = s.images.filter((x) => x !== decodeURIComponent(picture));
    return page(false);
  });
  on("POST", "/stream-control/music", (_p, body) => {
    if (body.files.some((f) => !/\.mp3$/i.test(f))) throw new HttpError(422, "The music has to be MP3 files.");
    m().music = [...new Set([...m().music, ...body.files])].sort();
    return [201, page(false)];
  });
  on("DELETE", "/stream-control/music/:name", ({ name }, _b, q) => {
    requireConfirm(q);
    m().music = m().music.filter((x) => x !== decodeURIComponent(name));
    return page(false);
  });
  // ------------------------------------------------------------------ the plugin API: what a stream plugin reads (stream:read)
  on("GET", "/plugin-api/v1/stream/design", (_p, _b, _q, h) => {
    const caller = pluginNeeds(h, "stream:read");
    if (!state().enabled || !isChosen(caller.id)) return { enabled: false };
    const { path: _, ...files } = media();
    return { enabled: true, design: design(), media: files };
  });

  // the pictures, as stand-ins (no fonts or tracks: the page falls back to its kind of font, and a track won't play)
  fileRoutes.push(
    [/^\/stream-control\/pictures\/([^/]+)$/, (x) => standIn(decodeURIComponent(x[1]))],
    [/^\/stream-control\/slideshows\/([^/]+)\/pictures\/([^/]+)$/, (x) => standIn(decodeURIComponent(x[2]))],
  );
  return {};
}
