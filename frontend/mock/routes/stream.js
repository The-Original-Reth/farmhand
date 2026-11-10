// The Stream page: sending a grid of cameras and cards live to YouTube or Twitch, the stream folder's pictures and
// slideshows, and the YouTube broadcast's
// title and description. The mockup sends nothing anywhere: Go live just says it's live, after the same checks the real
// server makes. The stream key and the Google client secret are kept only as "one is saved". Signing in to YouTube shows
// a made-up code and counts as done a few seconds later; the stream folder is kept in memory, sample pictures standing in
// for the files uploaded.
import { HttpError } from "../core.js";

const DESTINATIONS = { youtube: "YouTube Live", twitch: "Twitch" };
const KEY_SHAPE = /^[A-Za-z0-9_\-?=&.]{4,200}$/;
const CLIENT_ID_SHAPE = /^[A-Za-z0-9\-_.]{3,200}\.apps\.googleusercontent\.com$/;
const CAMERA_KEY = /^\d+:.{1,100}$/;
const SECONDS = { seconds_all: [0, 3600], seconds_each: [3, 3600] };
const SIGN_IN_TAKES_MS = 6000;
const RESOLUTIONS = { "720p": "720p (1280×720)", "1080p": "1080p (1920×1080)", "1440p": "2K (2560×1440)" };
const MAX_SIDE = 5;
const PICTURES = ["frog-vt1190", "shark-v2bog", "shark-vt1190"]; // the sample pictures shown for the uploads, in turn
const PICTURE = ["destination", "cols", "rows", "cells", "show_status", "layout", "resolution", "seconds_all", "seconds_each", "border_color", "background"];
const CARD = { background: null, image: null, slideshow: null, seconds: 10, text: "", color: "#FFFFFF", size: "medium", position: "middle" };
const STREAM_DEFAULT = "/data/storage/stream";
const hex = (v, d) => (/^#[0-9A-Fa-f]{6}$/.test(v || "") ? v.toUpperCase() : d);
const fileName = (v) => (typeof v === "string" && /^[^/\\]{1,120}$/.test(v) && v !== "." && v !== ".." ? v : null);
const natural = (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });

// the smallest near-square grid for n squares, as the server works it out
const autoGrid = (n) => {
  const cols = Math.min(MAX_SIDE, Math.max(1, Math.ceil(Math.sqrt(n))));
  return [cols, Math.min(MAX_SIDE, Math.max(1, Math.ceil(n / cols)))];
};

export function streamRoutes(ctx) {
  const { farm, fileRoutes, on, png } = ctx;
  const state = () =>
    (farm.stream ??= {
      destination: "youtube", cols: 1, rows: 1, cells: [null], show_status: true, layout: "grid", resolution: "1080p", seconds_all: 30,
      seconds_each: 20, border_color: "#000000", background: "#000000", title: "", description: "", key_set: false,
      images: [], slideshows: [], uploads: 0, location: null,
      live: false, started_at: null, labels: [], title_status: null,
      youtube: { client_id: null, signed_in: false, channel: null, signing_in: null, error: null },
    });
  const camerasOf = (s) => s.cells.filter((x) => x?.camera).map((x) => x.camera);
  const youtube = () => {
    const y = state().youtube;
    if (y.signing_in && Date.now() > y.signing_in.done_at) Object.assign(y, { signed_in: true, channel: "3D Printing Elves (mockup)", signing_in: null });
    return {
      client_set: !!y.client_id, client_id: y.client_id, signed_in: y.signed_in, channel: y.channel, error: y.error,
      signing_in: y.signing_in && { user_code: y.signing_in.user_code, verification_url: "https://www.google.com/device" },
    };
  };
  const page = () => {
    const s = state();
    return {
      settings: {
        destination: s.destination, cols: s.cols, rows: s.rows, cells: s.cells, cameras: camerasOf(s), show_status: s.show_status, layout: s.layout,
        resolution: s.resolution, seconds_all: s.seconds_all, seconds_each: s.seconds_each, border_color: s.border_color, background: s.background,
        title: s.title, description: s.description, key_set: s.key_set,
      },
      status: {
        live: s.live, on_air: s.live, started_at: s.started_at, destination: s.live ? s.destination : null, cameras: s.live ? s.labels : [],
        error: null, title: s.live ? s.title_status : null,
      },
      destinations: Object.entries(DESTINATIONS).map(([key, label]) => ({ key, label })),
      resolutions: Object.entries(RESOLUTIONS).map(([key, label]) => ({ key, label })),
      media: {
        path: s.location || STREAM_DEFAULT, error: null, images: s.images.map((x) => x.name).sort(natural),
        slideshows: [...s.slideshows].sort((a, b) => natural(a.name, b.name)).map((x) => ({ name: x.name, images: x.images.map((i) => i.name).sort(natural) })),
      },
      youtube: youtube(),
    };
  };
  const titleOutcome = () => {
    const s = state();
    if (s.destination !== "youtube" || !(s.title || s.description)) return null;
    if (!s.youtube.signed_in) return { state: "failed", message: "Sign in to YouTube (below) for Farmhand to set the title and description." };
    return { state: "done", message: `Title and description set on “${s.title || "Live"}”.` };
  };
  const goLive = () => {
    const s = state();
    if (!s.key_set) throw new HttpError(422, `Add your ${DESTINATIONS[s.destination]} stream key first.`);
    const cameras = camerasOf(s);
    if (!cameras.length) throw new HttpError(422, "Put at least one camera in the grid.");
    s.labels = cameras.map((k) => {
      const [id, name] = [k.slice(0, k.indexOf(":")), k.slice(k.indexOf(":") + 1)];
      const p = farm.printers.find((x) => x.id === Number(id));
      if (!p) throw new HttpError(422, "A chosen camera's printer is gone. Untick it and save.");
      return cameras.filter((c) => c.startsWith(`${id}:`)).length > 1 ? `${p.name} · ${name}` : p.name;
    });
    s.live = true;
    s.started_at = new Date().toISOString();
    s.title_status = titleOutcome();
  };
  const youtubeText = (text, most, what) => {
    const t = String(text).trim();
    if (t.length > most) throw new HttpError(422, `YouTube allows a ${what} of up to ${most} characters; this one has ${t.length}.`);
    if (/[<>]/.test(t)) throw new HttpError(422, `YouTube doesn't allow < or > in a ${what}.`);
    return t;
  };
  // the squares as sent, checked as the server checks them
  const checkCells = (cols, rows, cells) => {
    const side = (v) => Number.isInteger(v) && v >= 1 && v <= MAX_SIDE;
    if (!side(cols) || !side(rows)) throw new HttpError(422, `The grid can be 1 to ${MAX_SIDE} squares across and 1 to ${MAX_SIDE} down.`);
    if (!Array.isArray(cells) || cells.length !== cols * rows) throw new HttpError(422, `Say what's in each of the grid's ${cols * rows} squares.`);
    const seen = new Set();
    return cells.map((x) => {
      if (x == null) return null;
      if (typeof x.camera === "string" && CAMERA_KEY.test(x.camera)) {
        if (seen.has(x.camera)) throw new HttpError(422, "A camera can only be in one square.");
        seen.add(x.camera);
        return { camera: x.camera };
      }
      if (["background", "image", "slideshow", "text"].some((k) => k in x)) {
        if (x.image && x.slideshow) throw new HttpError(422, "A square shows a picture or a slideshow, not both.");
        const text = typeof x.text === "string" ? x.text.trim() : "";
        if (text.length > 500) throw new HttpError(422, `A square's text can be up to 500 characters; this one has ${text.length}.`);
        if (x.seconds != null && !(Number.isInteger(x.seconds) && x.seconds >= 3 && x.seconds <= 3600)) throw new HttpError(422, "A slideshow shows each picture for 3 to 3600 seconds.");
        return {
          ...CARD, background: hex(x.background, null), image: x.slideshow ? null : fileName(x.image), slideshow: fileName(x.slideshow),
          seconds: x.seconds ?? 10, text, color: hex(x.color, "#FFFFFF"), size: ["small", "medium", "large"].includes(x.size) ? x.size : "medium",
          position: ["top", "middle", "bottom"].includes(x.position) ? x.position : "middle",
        };
      }
      throw new HttpError(422, "A square can hold a camera, a colour, a picture or a slideshow with words over it, or nothing.");
    });
  };

  on("GET", "/stream", () => page());
  on("PUT", "/stream", (_, body) => {
    const s = state();
    const before = JSON.stringify(PICTURE.map((k) => s[k]));
    const titleBefore = s.title + "\n" + s.description;
    if (body.destination != null) {
      if (!DESTINATIONS[body.destination]) throw new HttpError(422, "Choose YouTube Live or Twitch.");
      s.destination = body.destination;
    }
    if (body.cells != null || body.cols != null || body.rows != null) {
      const cols = body.cols ?? s.cols;
      const rows = body.rows ?? s.rows;
      s.cells = checkCells(cols, rows, body.cells ?? s.cells);
      Object.assign(s, { cols, rows });
    } else if (Array.isArray(body.cameras)) {
      const keys = [...new Set(body.cameras.filter((k) => typeof k === "string" && CAMERA_KEY.test(k)))];
      if (keys.length > MAX_SIDE * MAX_SIDE) throw new HttpError(422, `A stream can show up to ${MAX_SIDE * MAX_SIDE} cameras at once.`);
      [s.cols, s.rows] = autoGrid(keys.length);
      s.cells = [...keys.map((k) => ({ camera: k })), ...Array(s.cols * s.rows - keys.length).fill(null)];
    }
    if (typeof body.show_status === "boolean") s.show_status = body.show_status;
    if (body.background != null) {
      if (!/^#[0-9A-Fa-f]{6}$/.test(body.background)) throw new HttpError(422, "Choose the stream's background colour with the colour picker (#RRGGBB).");
      s.background = body.background.toUpperCase();
    }
    if (body.border_color != null) {
      if (!/^#[0-9A-Fa-f]{6}$/.test(body.border_color)) throw new HttpError(422, "Choose the border's colour with the colour picker (#RRGGBB).");
      s.border_color = body.border_color.toUpperCase();
    }
    if (body.resolution != null) {
      if (!RESOLUTIONS[body.resolution]) throw new HttpError(422, "Choose 720p, 1080p or 2K.");
      s.resolution = body.resolution;
    }
    if (body.layout != null) {
      if (!["grid", "cycle"].includes(body.layout)) throw new HttpError(422, "Choose the whole grid, or taking turns.");
      s.layout = body.layout;
    }
    for (const [name, [least, most]] of Object.entries(SECONDS)) {
      if (body[name] == null) continue;
      if (!Number.isInteger(body[name]) || body[name] < least || body[name] > most) {
        throw new HttpError(422, `The time for ${name === "seconds_all" ? "showing the whole grid" : "each camera"} has to be from ${least} to ${most} seconds.`);
      }
      s[name] = body[name];
    }
    if (body.title != null) s.title = youtubeText(body.title, 100, "title");
    if (body.description != null) s.description = youtubeText(body.description, 5000, "description");
    if (body.clear_key) s.key_set = false;
    else if (body.stream_key && body.stream_key.trim()) {
      if (!KEY_SHAPE.test(body.stream_key.trim())) throw new HttpError(422, "That doesn't look like a stream key. Copy it again from YouTube Studio (Go live → Stream → Stream key).");
      s.key_set = true;
    }
    const after = JSON.stringify(PICTURE.map((k) => s[k]));
    if (s.live && (before !== after || body.stream_key)) goLive();
    else if (s.live && titleBefore !== s.title + "\n" + s.description) s.title_status = titleOutcome();
    return page();
  });
  on("POST", "/stream/start", () => {
    goLive();
    return page();
  });
  on("POST", "/stream/stop", () => {
    Object.assign(state(), { live: false, started_at: null, labels: [], title_status: null });
    return page();
  });

  // the stream folder: pictures and slideshows, kept in memory, named after the files sent; sample pictures stand in
  const upload = (names, into) => {
    const s = state();
    for (const name of names) {
      if (!/\.(png|jpe?g|webp)$/i.test(name)) throw new HttpError(422, "A picture has to be a PNG, JPEG or WebP file.");
      let candidate = name;
      for (let n = 2; into.some((x) => x.name.toLowerCase() === candidate.toLowerCase()); n++) candidate = name.replace(/(\.[^.]+)$/, ` (${n})$1`);
      into.push({ name: candidate, picture: PICTURES[s.uploads++ % PICTURES.length] });
    }
  };
  const showOf = (name) => state().slideshows.find((x) => x.name === decodeURIComponent(name));
  const confirm = (q) => {
    if (q.get("confirm") !== "true") throw new HttpError(409, "Deleting is permanent — pass confirm=true to proceed");
  };
  on("POST", "/stream/pictures", (_, body) => {
    upload(body.files || [], state().images);
    return page();
  });
  on("DELETE", "/stream/pictures/:name", ({ name }, _b, q) => {
    confirm(q);
    const s = state();
    if (!s.images.some((x) => x.name === decodeURIComponent(name))) throw new HttpError(404, "That picture isn't there.");
    s.images = s.images.filter((x) => x.name !== decodeURIComponent(name));
    return page();
  });
  on("POST", "/stream/slideshows", (_, body) => {
    const s = state();
    const name = String(body.name || "").trim();
    if (!fileName(name) || name.startsWith(".")) throw new HttpError(422, "That isn't a name a slideshow can have.");
    if (s.slideshows.some((x) => x.name.toLowerCase() === name.toLowerCase())) throw new HttpError(422, `There's already a slideshow called “${name}”.`);
    s.slideshows.push({ name, images: [] });
    return page();
  });
  on("DELETE", "/stream/slideshows/:name", ({ name }, _b, q) => {
    confirm(q);
    if (!showOf(name)) throw new HttpError(404, "That slideshow isn't there.");
    state().slideshows = state().slideshows.filter((x) => x.name !== decodeURIComponent(name));
    return page();
  });
  on("POST", "/stream/slideshows/:name/pictures", ({ name }, body) => {
    const s = state();
    if (!showOf(name)) s.slideshows.push({ name: decodeURIComponent(name), images: [] });
    upload(body.files || [], showOf(name).images);
    return page();
  });
  on("DELETE", "/stream/slideshows/:name/pictures/:picture", ({ name, picture }, _b, q) => {
    confirm(q);
    const show = showOf(name);
    if (!show || !show.images.some((x) => x.name === decodeURIComponent(picture))) throw new HttpError(404, "That picture isn't there.");
    show.images = show.images.filter((x) => x.name !== decodeURIComponent(picture));
    return page();
  });
  fileRoutes.push([/^\/stream\/pictures\/([^/]+)$/, (m) => png(state().images.find((x) => x.name === decodeURIComponent(m[1]))?.picture)]);
  fileRoutes.push([/^\/stream\/slideshows\/([^/]+)\/pictures\/([^/]+)$/, (m) => png(showOf(m[1])?.images.find((x) => x.name === decodeURIComponent(m[2]))?.picture)]);

  // where the stream folder is (Settings)
  const locationOut = () => {
    const s = state();
    return { path: s.location || STREAM_DEFAULT, is_default: !s.location, default_path: STREAM_DEFAULT, status: { exists: true, writable: true, marker_ok: true, ready: true } };
  };
  on("GET", "/stream/location", () => locationOut());
  on("PUT", "/stream/location", (_, body) => {
    state().location = body.path || null;
    return locationOut();
  });

  // signing in to YouTube
  on("PUT", "/stream/youtube", (_, body) => {
    const y = state().youtube;
    const id = String(body.client_id || "").trim();
    if (!CLIENT_ID_SHAPE.test(id)) throw new HttpError(422, "That doesn't look like a Google client ID: it ends in .apps.googleusercontent.com.");
    if (!String(body.client_secret || "").trim() && y.client_id !== id) throw new HttpError(422, "Paste the client secret too (from the same OAuth client in Google Cloud).");
    if (y.client_id !== id) Object.assign(y, { signed_in: false, channel: null, signing_in: null });
    y.client_id = id;
    y.error = null;
    return page();
  });
  on("POST", "/stream/youtube/sign-in", () => {
    const y = state().youtube;
    if (!y.client_id) throw new HttpError(422, "Add the Google OAuth client ID and secret first.");
    y.signing_in = { user_code: "MOCK-CODE", done_at: Date.now() + SIGN_IN_TAKES_MS };
    y.error = null;
    return page();
  });
  on("POST", "/stream/youtube/sign-out", (_, body) => {
    const y = state().youtube;
    Object.assign(y, { signed_in: false, channel: null, signing_in: null, error: null });
    if (body.forget_client) y.client_id = null;
    return page();
  });
  on("POST", "/stream/youtube/apply", () => {
    const s = state();
    if (!s.youtube.signed_in) throw new HttpError(422, "Sign in to YouTube first.");
    if (!(s.title || s.description)) throw new HttpError(422, "Write a title or description first, and save it.");
    if (s.live) s.title_status = titleOutcome();
    return page();
  });
  return {};
}
