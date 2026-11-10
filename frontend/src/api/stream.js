// The Stream page: printers' cameras sent live to YouTube or Twitch by Farmhand itself, laid out in a grid of squares,
// and the YouTube broadcast's own title and description. The stream key, the Google client secret and the YouTube
// sign-in are sent once and never come back: the page only learns whether each is there.
import { API_BASE, del, jsonBody, post, request } from "./client.js";

// { settings: { destination, cols, rows, cells: [per square, row by row: { camera: "printer id:camera name" } | a card
// { background, image, slideshow, seconds, text, color, picture_box: { x, y, w, h }, text_box: { x, y, size } (parts of the square) }; a camera may have its own background too | null], cameras (the cameras in square order), showStatus, layout: "grid" | "cycle", resolution,
// secondsAll, secondsEach, borderColor: "#RRGGBB", background (the stream's colour), title, description, keySet },
// status: { live, onAir, startedAt, destination, cameras: [labels], error, title: { state: "waiting" | "done" |
// "failed", message } | null }, destinations: [{ key, label }], resolutions: [{ key: "720p" | "1080p" | "1440p", label }], fonts: [{ key, label, generic }] (what a square's words can be written in),
// media: { path, windows_path (the stream folder as Windows reaches it over the network, or null), images: [file names], slideshows: [{ name, images: [file names] }], error } (the stream folder), youtube: { clientSet, clientId, signedIn, channel, signingIn: { userCode, verificationUrl } |
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
    title: s.settings.title,
    description: s.settings.description,
    keySet: s.settings.key_set,
  },
  status: {
    live: s.status.live,
    onAir: s.status.on_air,
    startedAt: s.status.started_at,
    destination: s.status.destination,
    cameras: s.status.cameras,
    error: s.status.error,
    title: s.status.title || null,
  },
  destinations: s.destinations,
  resolutions: s.resolutions,
  fonts: s.fonts || [],
  media: s.media,
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
// secondsEach, borderColor, background, title, description, streamKey (blank: keep the saved one),
// clearKey }. While live, a new picture starts the stream again; a new title is set on YouTube straight away.
export const saveStream = async (s = {}) =>
  normalizeStream(
    await request(
      "/stream",
      jsonBody("PUT", {
        destination: s.destination, cols: s.cols, rows: s.rows, cells: s.cells, show_status: s.showStatus, layout: s.layout,
        resolution: s.resolution, seconds_all: s.secondsAll, seconds_each: s.secondsEach, border_color: s.borderColor, background: s.background,
        title: s.title, description: s.description,
        stream_key: s.streamKey || null, clear_key: !!s.clearKey,
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
export const uploadStreamPictures = async (files) => normalizeStream(await request("/stream/pictures", filesBody(files)));
export const removeStreamPicture = async (name) => normalizeStream(await del(`/stream/pictures/${enc(name)}`));
export const createSlideshow = async (name) => normalizeStream(await request("/stream/slideshows", jsonBody("POST", { name })));
export const removeSlideshow = async (name) => normalizeStream(await del(`/stream/slideshows/${enc(name)}`));
export const uploadSlideshowPictures = async (show, files) => normalizeStream(await request(`/stream/slideshows/${enc(show)}/pictures`, filesBody(files)));
export const removeSlideshowPicture = async (show, name) => normalizeStream(await del(`/stream/slideshows/${enc(show)}/pictures/${enc(name)}`));

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

// The slideshow folders: each a name and images (PNG or JPEG under 1 MB each) shown in turn in a square. Deleting a
// folder empties the squares showing it.
export const folderImageUrl = (folderId, imageId) => `${API_BASE}/stream/folders/${folderId}/images/${imageId}`;
export const createStreamFolder = async (name) => normalizeStream(await request("/stream/folders", jsonBody("POST", { name })));
export const removeStreamFolder = async (id) => normalizeStream(await del(`/stream/folders/${id}`));
export const uploadFolderImages = async (folderId, files) => {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  return normalizeStream(await request(`/stream/folders/${folderId}/images`, { method: "POST", body: form }));
};
export const removeFolderImage = async (folderId, imageId) => normalizeStream(await del(`/stream/folders/${folderId}/images/${imageId}`));
