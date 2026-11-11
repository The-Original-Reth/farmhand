// The Stream page: printers' cameras sent live to YouTube by Farmhand itself, laid out in a grid of squares,
// and the YouTube broadcast's own title and description. The stream key, the Google client secret and the YouTube
// sign-in are sent once and never come back: the page only learns whether each is there.
import { API_BASE, del, jsonBody, post, request } from "./client.js";

// { settings: { destination, cols, rows, cells: [per square, row by row: { camera: "printer id:camera name" } | a card
// { background, image, slideshow, seconds, text, color, picture_box: { x, y, w, h }, text_box: { x, y, size } (parts of the square) }; a camera may have its own background too | null], cameras (the cameras in square order), showStatus, layout: "grid" | "cycle", resolution,
// secondsAll, secondsEach, borderColor: "#RRGGBB", background (the stream's colour), font and color (its words'), music (the stream folder's music
// played, or a silent sound track), musicVolume (0 to 100), musicShuffle, title, description, keySet },
// status: { live, onAir, startedAt, destination, cameras: [labels], error, title: { state: "waiting" | "done" |
// "failed", message } | null }, destinations: [{ key, label }], resolutions: [{ key: "720p" | "1080p" | "1440p", label }], fonts: [{ key, label, generic }] (what a square's words can be written in),
// media: { path, windows_path (the stream folder as Windows reaches it over the network, or null), images: [file names], slideshows: [{ name, images: [file names] }], music: [MP3s' file names], error } (the stream folder), youtube: { clientSet, clientId, signedIn, channel, signingIn: { userCode, verificationUrl } |
// null, error } }
const normalizeStream = (s) => ({
  settings: {
    destination: s.settings.destination,
    cols: s.settings.cols,
    rows: s.settings.rows,
    cells: s.settings.cells,
    cameras: s.settings.cameras,
    showStatus: s.settings.show_status,
    layout: s.settings.layout,
    resolution: s.settings.resolution,
    secondsAll: s.settings.seconds_all,
    secondsEach: s.settings.seconds_each,
    borderColor: s.settings.border_color,
    background: s.settings.background,
    font: s.settings.font, // the stream's words: every square's and camera's unless it has its own
    color: s.settings.color,
    music: !!s.settings.music,
    musicVolume: s.settings.music_volume ?? 50,
    musicShuffle: s.settings.music_shuffle !== false,
    delay: s.settings.delay ?? 60, // seconds the stream is held before YouTube gets it (0 to 120)
    title: s.settings.title,
    description: s.settings.description,
    keySet: s.settings.key_set,
    enabled: s.settings.enabled !== false, // the page's switch: off, nothing streams and the page rests
  },
  status: {
    live: s.status.live,
    onAir: s.status.on_air,
    startedAt: s.status.started_at,
    destination: s.status.destination,
    cameras: s.status.cameras,
    error: s.status.error,
    title: s.status.title || null,
    encoder: s.status.encoder || null, // "nvenc" (an NVIDIA card compresses it) or "cpu", while live
    // how long the picture going out has run (s), and when that was heard: the preview counts from the same start
    runningFor: typeof s.status.running_for === "number" ? s.status.running_for : null,
    // the server's time of day (s): slideshows and taking turns count from it, on the stream and in the preview
    serverTime: typeof s.status.server_time === "number" ? s.status.server_time : null,
    heardAt: Date.now(),
    // the music going out, while live: { on, playing, track (its file name, null before the first), at (s into it) }
    music: s.status.music || null,
    // the delay before YouTube, while live: { seconds, held (seconds held now), filling (nothing sent to YouTube yet) }
    delay: s.status.delay || null,
    // a new layout is on its way (waiting a moment for more changes, then warming up beside the one going out)
    changing: !!s.status.changing,
  },
  destinations: s.destinations,
  resolutions: s.resolutions,
  fonts: s.fonts || [],
  media: { ...s.media, music: s.media.music || [] },
  youtube: {
    clientSet: s.youtube.client_set,
    clientId: s.youtube.client_id,
    signedIn: s.youtube.signed_in,
    channel: s.youtube.channel,
    signingIn: s.youtube.signing_in && { userCode: s.youtube.signing_in.user_code, verificationUrl: s.youtube.signing_in.verification_url },
    error: s.youtube.error,
  },
});

export const getStream = async () => normalizeStream(await request("/stream"));

// Save what's given: { destination, cols, rows, cells (the three together), showStatus, layout, resolution, secondsAll,
// secondsEach, borderColor, background, font, color, music, musicVolume, musicShuffle, title, description, streamKey (blank: keep the saved one),
// clearKey, enabled (the page's switch: false stops the stream) }. While live, a new picture starts the stream again; a new title is set on YouTube straight away.
export const saveStream = async (s = {}) =>
  normalizeStream(
    await request(
      "/stream",
      jsonBody("PUT", {
        destination: s.destination, cols: s.cols, rows: s.rows, cells: s.cells, show_status: s.showStatus, layout: s.layout,
        resolution: s.resolution, seconds_all: s.secondsAll, seconds_each: s.secondsEach, border_color: s.borderColor, background: s.background, font: s.font, color: s.color,
        title: s.title, description: s.description, music: s.music, music_volume: s.musicVolume, music_shuffle: s.musicShuffle, delay: s.delay,
        stream_key: s.streamKey || null, clear_key: !!s.clearKey, enabled: s.enabled,
      }),
    ),
  );

export const startStream = async () => normalizeStream(await post("/stream/start"));
export const stopStream = async () => normalizeStream(await post("/stream/stop"));

// The stream folder's pictures, as files: single pictures in images/, each slideshow a folder in slideshows/ (PNG, JPEG or
// WebP; uploads under 10 MB). Files dropped into the folder by hand count too.
const enc = encodeURIComponent;
const filesBody = (files) => {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  return { method: "POST", body: form };
};
// a font a square's words can be written in, as the server has it (for the page to show them as the stream does)
export const streamFontUrl = (key) => `${API_BASE}/stream/fonts/${enc(key)}`;
export const streamPictureUrl = (name) => `${API_BASE}/stream/pictures/${enc(name)}`;
export const slideshowPictureUrl = (show, name) => `${API_BASE}/stream/slideshows/${enc(show)}/pictures/${enc(name)}`;
// read the stream folder again (pictures copied in or taken out by hand): the server doesn't keep looking at it
export const scanStreamFolder = async () => normalizeStream(await post("/stream/scan"));
export const uploadStreamPictures = async (files) => normalizeStream(await request("/stream/pictures", filesBody(files)));
export const removeStreamPicture = async (name) => normalizeStream(await del(`/stream/pictures/${enc(name)}`));
export const createSlideshow = async (name) => normalizeStream(await request("/stream/slideshows", jsonBody("POST", { name })));
// a slideshow's new name: its folder is renamed, and every square showing it (on the page and in saved layouts) follows
export const renameSlideshow = async (show, name) => normalizeStream(await request(`/stream/slideshows/${enc(show)}`, jsonBody("PUT", { name })));
export const removeSlideshow = async (name) => normalizeStream(await del(`/stream/slideshows/${enc(name)}`));
export const uploadSlideshowPictures = async (show, files) => normalizeStream(await request(`/stream/slideshows/${enc(show)}/pictures`, filesBody(files)));
// a blank screen at the end of a slideshow: its colour and the words written on it (deleted as a picture is)
export const addSlideshowBlank = async (show) => normalizeStream(await post(`/stream/slideshows/${enc(show)}/blanks`));
// a slideshow's pictures in the order chosen (kept in its folder)
export const orderSlideshow = async (show, order) => normalizeStream(await request(`/stream/slideshows/${enc(show)}/order`, jsonBody("PUT", { order })));
export const removeSlideshowPicture = async (show, name) => normalizeStream(await del(`/stream/slideshows/${enc(show)}/pictures/${enc(name)}`));

// The stream's music: MP3s in the stream folder's music folder (uploads under 50 MB), played one after another, round
// and round, starting with the stream. Tracks added while live join its next round.
// While live: "play", "pause", "next" or "back" (the track from its start, or in its first 3 s the one before).
export const musicControl = async (action) => normalizeStream(await post(`/stream/music/${action}`));
export const streamTrackUrl = (name) => `${API_BASE}/stream/music/${enc(name)}`;
export const uploadStreamMusic = async (files) => normalizeStream(await request("/stream/music", filesBody(files)));
export const removeStreamTrack = async (name) => normalizeStream(await del(`/stream/music/${enc(name)}`));

// Where the stream folder is (Settings): { path, isDefault, defaultPath, status: { exists, writable, markerOk, ready } }.
// setStreamLocation(null) goes back to the default; a folder that can't be used is refused with the reason.
const normalizeLocation = (l) => ({
  path: l.path, isDefault: l.is_default, defaultPath: l.default_path,
  status: { exists: l.status.exists, writable: l.status.writable, markerOk: l.status.marker_ok, ready: l.status.ready },
});
export const getStreamLocation = async () => normalizeLocation(await request("/stream/location"));
export const setStreamLocation = async (path) => normalizeLocation(await request("/stream/location", jsonBody("PUT", { path })));

// Signing in to YouTube: the Google OAuth client (a blank secret keeps the saved one), then a code to enter at
// google.com/device (getStream finishes the sign-in once it's entered), and signing out.
export const saveYouTubeClient = async ({ clientId, clientSecret }) =>
  normalizeStream(await request("/stream/youtube", jsonBody("PUT", { client_id: clientId, client_secret: clientSecret || null })));
export const youtubeSignIn = async () => normalizeStream(await post("/stream/youtube/sign-in"));
export const youtubeSignOut = async (forgetClient = false) =>
  normalizeStream(await request("/stream/youtube/sign-out", jsonBody("POST", { forget_client: forgetClient })));
// Set the saved title and description on the live broadcast now
export const youtubeApply = async () => normalizeStream(await post("/stream/youtube/apply"));
