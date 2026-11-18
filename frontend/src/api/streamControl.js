// Stream control, the plugin built into Farmhand: one stream designed here (its grid of cameras and cards, words,
// colours, music and holding screen), which the stream plugins (YouTube, Twitch) each send to their own site; starting
// and stopping them, one at a time or all at once; the schedule; and the stream folder's pictures and music. Every call
// answers 404 while Stream control is switched off (the Plugins page: changePlugin("stream-control", { enabled })).
import { API_BASE, del, jsonBody, post, request } from "./client.js";

const enc = encodeURIComponent;

// The design as the page's controls use it (the Stream plugins' page names, so the editor copied from them reads it as is):
// { cols, rows, cells: [per square, row by row: { camera: "printer id:camera name", ... } | a card { background, image,
// slideshow, seconds, text, color, font, band, picture_box, text_box, captions, picture_boxes, layers, slide_layers } |
// null], cameras, showStatus, layout: "grid" | "cycle", resolution, secondsAll, secondsEach, borderColor, background,
// font, color, music, musicVolume, musicShuffle, delay (seconds each plugin holds the stream before its site gets it),
// holding: { text, image, background, color, font }, title, description, revision (one more each save), savedAt }
export const normalizeDesign = (d) => ({
  cols: d.cols,
  rows: d.rows,
  cells: d.cells,
  cameras: d.cameras,
  showStatus: d.show_status,
  layout: d.layout,
  resolution: d.resolution,
  secondsAll: d.seconds_all,
  secondsEach: d.seconds_each,
  borderColor: d.border_color,
  background: d.background,
  font: d.font,
  color: d.color,
  music: !!d.music,
  musicVolume: d.music_volume ?? 50,
  musicShuffle: d.music_shuffle !== false,
  musicFrom: d.music_from || ["stream-control"], // the music folders played: "stream-control" (its own) and/or stream plugins' ids
  delay: d.delay ?? 60,
  holding: { text: "Back in a minute", image: null, background: null, color: null, font: null, ...(d.holding || {}) },
  title: d.title || "",
  description: d.description || "",
  revision: d.revision || 0,
  savedAt: d.saved_at || null,
});

// A stream plugin and how its stream is doing: { id, name, site ("YouTube"), enabled (switched on, on the Plugins page),
// chosen (brought into Stream control: sent its design, started and stopped from here),
// live, following (it sends the stream designed here; false: its own layout; null: not known), error, watchUrl,
// reachable (null: switched off, so not asked), canReadDesign (granted stream:read), hasPage }
export const normalizeStreamPlugin = (s) => ({
  id: s.id, name: s.name, site: s.site, enabled: s.enabled, chosen: s.chosen !== false, live: s.live, following: s.following, error: s.error || null,
  watchUrl: s.watch_url || null, reachable: s.reachable, canReadDesign: !!s.can_read_design, hasPage: !!s.has_page,
  needsUpdate: !!s.needs_update, // a version from before Stream control: it starts and stops from here, but sends its own layout
  // as its own page shows them: [{ label, url, title }] (Watch, Chat, Stream Manager...), each camera's state while live
  // [{ key, label, state: "live" | "down" | "starting", since }], and YouTube's viewers (null: not known)
  links: s.links || [], cameras: s.cameras || [], viewers: s.viewers ?? null,
  settingsPage: s.settings_page || null, // its site's settings window, a page of its own ("/?view=youtube-settings")
});

// What the schedule did lately: [{ at, action: "start" | "stop", streams: "all" | [ids], results: [{ name, live, error }] }]
const normalizeHappened = (h) => h || [];

// The whole page: { design, resolutions: [{ key, label }], fonts: [{ key, label, generic }], media: { path, images,
// slideshows: [{ name, images }], music, error } (the stream folder), layouts (the saved ones, as the server keeps them),
// schedule: { on, entries: [{ days: [0 (Monday) to 6], start: "HH:MM" | null, stop, streams: "all" | [ids] }] },
// happened, timeZone (the farm's: the schedule's times are in it), streams: [stream plugins] }
// A part answered alone (after a change to the stream folder, layouts or schedule) comes with streams: null (not asked).
const normalizePage = (p) => ({
  design: normalizeDesign(p.design),
  resolutions: p.resolutions,
  fonts: p.fonts || [],
  // music: the stream's tracks from the folders chosen; ownMusic: those in Stream control's own folder (only those can be
  // deleted here); musicSources: [{ id, label, chosen, tracks, problem }], the folders there are to choose from
  media: { ...p.media, music: p.media.music || [], ownMusic: p.media.own_music || [], musicSources: p.media.music_sources || [], musicTracks: p.media.music_tracks || [] },
  layouts: p.layouts || [],
  schedule: p.schedule,
  happened: normalizeHappened(p.happened),
  timeZone: p.time_zone || null,
  streams: p.streams ? p.streams.map(normalizeStreamPlugin) : null,
});

export const getStreamControl = async () => normalizePage(await request("/stream-control"));

// Save what's given of the design (camelCase, as normalizeDesign): anything left out stays as it was
export const saveStreamDesign = async (s = {}) =>
  normalizePage(
    await request(
      "/stream-control",
      jsonBody("PUT", {
        cols: s.cols, rows: s.rows, cells: s.cells, cameras: s.cameras, show_status: s.showStatus, layout: s.layout,
        resolution: s.resolution, seconds_all: s.secondsAll, seconds_each: s.secondsEach, border_color: s.borderColor,
        background: s.background, font: s.font, color: s.color, music: s.music, music_volume: s.musicVolume,
        music_shuffle: s.musicShuffle, music_from: s.musicFrom, delay: s.delay, holding: s.holding, title: s.title, description: s.description,
      }),
    ),
  );

// The stream plugins: { streams, happened }
export const getStreamPlugins = async () => {
  const r = await request("/stream-control/streams");
  return { streams: r.streams.map(normalizeStreamPlugin), happened: normalizeHappened(r.happened) };
};
// Which stream plugins Stream control brings in (their ids; the others keep their own layout and aren't started or
// stopped from here): { streams, happened }
export const chooseStreamPlugins = async (ids) => {
  const r = await request("/stream-control/streams", jsonBody("PUT", { chosen: ids }));
  return { streams: r.streams.map(normalizeStreamPlugin), happened: normalizeHappened(r.happened) };
};
// Copy layout: this stream plugin's own layout made Stream control's (every stream brought in then shows it), its
// pictures and slideshows copied into the stream folder: { page, copied: [what was copied], problems: [what wasn't] }
export const copyStreamLayout = async (id) => {
  const r = await post(`/stream-control/streams/${enc(id)}/copy-layout`);
  return { page: normalizePage(r), copied: r.copied || [], problems: r.problems || [] };
};
// Start or stop one: its entry as it answered (error: why it didn't)
export const startStreamPlugin = async (id) => normalizeStreamPlugin(await post(`/stream-control/streams/${enc(id)}/start`));
export const stopStreamPlugin = async (id) => normalizeStreamPlugin(await post(`/stream-control/streams/${enc(id)}/stop`));
// All of them at once: each one's entry as it answered
export const startAllStreams = async () => (await post("/stream-control/start-all")).streams.map(normalizeStreamPlugin);
export const stopAllStreams = async () => (await post("/stream-control/stop-all")).streams.map(normalizeStreamPlugin);

export const saveStreamSchedule = async (schedule) => normalizePage(await request("/stream-control/schedule", jsonBody("PUT", schedule)));
export const saveStreamLayouts = async (layouts) => normalizePage(await request("/stream-control/layouts", jsonBody("PUT", layouts))).layouts;

// The stream folder: single pictures in images/, each slideshow a folder in slideshows/, MP3s in music/ (PNG, JPEG,
// WebP or SVG pictures under 10 MB; tracks under 50 MB). Files dropped into the folder by hand count too (Scan folder).
// Each change answers the page (without streams).
const filesBody = (files) => {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  return { method: "POST", body: form };
};
export const streamFontUrl = (key) => `${API_BASE}/stream-control/fonts/${enc(key)}`;
export const streamPictureUrl = (name) => `${API_BASE}/stream-control/pictures/${enc(name)}`;
export const slideshowPictureUrl = (show, name) => `${API_BASE}/stream-control/slideshows/${enc(show)}/pictures/${enc(name)}`;
export const streamTrackUrl = (name) => `${API_BASE}/stream-control/music/${enc(name)}`;
export const scanStreamFolder = async () => normalizePage(await post("/stream-control/scan"));
export const uploadStreamPictures = async (files) => normalizePage(await request("/stream-control/pictures", filesBody(files)));
export const removeStreamPicture = async (name) => normalizePage(await del(`/stream-control/pictures/${enc(name)}`));
export const createSlideshow = async (name) => normalizePage(await request("/stream-control/slideshows", jsonBody("POST", { name })));
// a slideshow's new name: its folder is renamed, and every square showing it (in the design and saved layouts) follows
export const renameSlideshow = async (show, name) => normalizePage(await request(`/stream-control/slideshows/${enc(show)}`, jsonBody("PUT", { name })));
export const removeSlideshow = async (name) => normalizePage(await del(`/stream-control/slideshows/${enc(name)}`));
export const uploadSlideshowPictures = async (show, files) => normalizePage(await request(`/stream-control/slideshows/${enc(show)}/pictures`, filesBody(files)));
export const addSlideshowBlank = async (show) => normalizePage(await post(`/stream-control/slideshows/${enc(show)}/blanks`));
export const orderSlideshow = async (show, order) => normalizePage(await request(`/stream-control/slideshows/${enc(show)}/order`, jsonBody("PUT", { order })));
export const removeSlideshowPicture = async (show, name) => normalizePage(await del(`/stream-control/slideshows/${enc(show)}/pictures/${enc(name)}`));
export const uploadStreamMusic = async (files) => normalizePage(await request("/stream-control/music", filesBody(files)));
export const removeStreamTrack = async (name) => normalizePage(await del(`/stream-control/music/${enc(name)}`));
