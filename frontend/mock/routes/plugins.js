// Plugins: the Plugins page's side (/plugins: a look at the plugin at an address, adding it, switching it off, a new
// token, removing it), a plugin's page passed on (the browser's /plugins/<id>/..., pluginPageRequest), and the plugin
// API v1 a plugin's container reads Farmhand through (/plugin-api/v1/, token- and permission-checked), in the real
// API's shapes (backend/app/routers/plugins.py, plugin_api.py; docs/plugins.md). Tokens are kept in memory by their
// value here; the real backend keeps only their hash.
//
// Pretend plugins are "on the network": Hello at http://192.168.10.215:8080 (added already, with a tiny page listing
// the printers) and Shelf clock at http://192.168.10.216:8080 (there to be added). Nothing else answers.
import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { paletteFor } from "../../src/appearance.js";
import { HttpError, NO_MOONRAKER } from "../core.js";

const API_VERSION = "1";
const PERMISSIONS = {
  "printers:read": "see your printers: their names, how Farmhand reaches them and their addresses (never passwords or API keys)",
  "cameras:read": "see your printers' cameras and the addresses to stream them from",
  "prints:read": "see what each printer is printing and how far along it is, and hear when a print starts, pauses or ends",
  "farm:read": "see Farmhand's colours and the farm's time zone",
};
const describe = (perms) => perms.filter((p) => p in PERMISSIONS).map((p) => ({ permission: p, means: PERMISSIONS[p] }));
const MJPEG = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "5",
  "-rw_timeout", "10000000", "-use_wallclock_as_timestamps", "1", "-f", "mpjpeg"];
const RTSP = ["-rtsp_transport", "tcp", "-timeout", "10000000"];
const NO_TOKEN = "This needs the plugin's token, sent as \"Authorization: Bearer <token>\" (the FARMHAND_TOKEN it was given).";
const BAD_TOKEN = "That plugin token isn't valid: it was replaced by a new one, the plugin was removed or turned off, or it was never made here. The operator can give the plugin a new token on Farmhand's Plugins page.";

// The manifest, checked as services/plugins/manifest.py does (the same messages)
function checkManifest(m) {
  const bad = (msg) => { throw new HttpError(422, msg); };
  if (!m || typeof m !== "object" || Array.isArray(m)) bad("The plugin's manifest (farmhand-plugin.json) isn't a JSON object.");
  if (typeof m.id !== "string" || !/^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/.test(m.id)) bad(`The plugin's id must be 1 to 40 lower-case letters, digits and dashes (not starting or ending with a dash), like "stream". This one is ${JSON.stringify(m.id)}.`);
  const text = (obj, key, longest, label = key, required = false) => {
    const v = obj[key];
    if (v == null && !required) return null;
    if (typeof v !== "string" || !v.trim() || v.length > longest) bad(`The plugin's ${label} must be text of 1 to ${longest} characters.`);
    return v.trim();
  };
  const path = (v, label) => {
    if (v == null) return null;
    if (typeof v !== "string" || !v.startsWith("/") || v.length > 200) bad(`The plugin's ${label} must be a path on the plugin starting with "/", like "/health".`);
    return v;
  };
  const name = text(m, "name", 80, "name", true);
  if (typeof m.version !== "string" || !/^[0-9A-Za-z][0-9A-Za-z.+-]{0,39}$/.test(m.version)) bad(`The plugin's version must be like "1.0.0". This one is ${JSON.stringify(m.version)}.`);
  if (m.farmhand_api !== API_VERSION) bad(`This plugin was written for Farmhand's plugin API version ${JSON.stringify(m.farmhand_api)}, and this Farmhand speaks version "${API_VERSION}". Look for a version of the plugin made for it.`);
  if (!Number.isInteger(m.port) || m.port < 1 || m.port > 65535) bad(`The plugin's port must be a whole number from 1 to 65535. This one is ${JSON.stringify(m.port)}.`);
  const perms = m.permissions ?? [];
  if (!Array.isArray(perms) || !perms.every((p) => typeof p === "string")) bad("The plugin's permissions must be a list, like [\"printers:read\"].");
  const unknown = perms.filter((p) => !(p in PERMISSIONS));
  if (unknown.length) bad(`The plugin asks for ${unknown.map((p) => `'${p}'`).join(", ")}, which this Farmhand doesn't know. It knows ${Object.keys(PERMISSIONS).join(", ")}.`);
  let page = null;
  if (m.page != null) {
    if (typeof m.page !== "object" || Array.isArray(m.page)) bad("The plugin's page must be an object, like {\"menu\": \"Stream\", \"path\": \"/\"}.");
    page = { menu: text(m.page, "menu", 40, "page menu", true), icon: text(m.page, "icon", 40, "page icon"), path: path(m.page.path ?? "/", "page path") };
  }
  return {
    id: m.id, name, version: m.version, farmhand_api: m.farmhand_api, port: m.port,
    author: text(m, "author", 120), homepage: text(m, "homepage", 300), permissions: [...new Set(perms)],
    page, settings_page: path(m.settings_page, "settings_page"), health: path(m.health, "health"),
  };
}

// The pretend plugins on the farm's network, by address: what GET <address>/manifest answers
const ON_THE_NETWORK = {
  "http://192.168.10.215:8080": {
    id: "hello", name: "Hello", version: "1.0.0", farmhand_api: "1", port: 8080, author: "Farmhand mockup", // plugins/hello's manifest
    page: { menu: "Hello", icon: "dashboard", path: "/" }, permissions: ["printers:read", "prints:read", "farm:read"], health: "/health",
  },
  "http://192.168.10.216:8080": {
    id: "shelf-clock", name: "Shelf clock", version: "1.2.0", farmhand_api: "1", port: 8080, author: "Farmhand mockup",
    homepage: "https://example.com/shelf-clock", page: { menu: "Shelf clock", path: "/" }, permissions: ["prints:read"], health: "/health",
  },
};
const UNREACHABLE = (address) => `Farmhand couldn't reach a plugin at ${address} (nothing answered there). Is it running, and is the address right?`;
// The address as services/plugins/remote.py tidies it (the same messages)
function tidyAddress(raw) {
  const example = "like http://192.168.10.215:8080";
  if (typeof raw !== "string" || !raw.trim()) throw new HttpError(422, `Type the plugin's address, ${example}.`);
  let text = raw.trim();
  if (!text.includes("://")) text = `http://${text}`;
  let u;
  try {
    u = new URL(text);
  } catch {
    throw new HttpError(422, `"${raw.trim()}" isn't an address Farmhand can use. Type it ${example}.`);
  }
  if (!["http:", "https:"].includes(u.protocol) || !u.hostname) throw new HttpError(422, `The plugin's address must start with http:// or https:// and name a machine, ${example}.`);
  if (u.username || u.password || u.search || u.hash) throw new HttpError(422, `The plugin's address can't have a password, ? or # in it. Type it ${example}.`);
  return `${u.protocol}//${u.host}${u.pathname.replace(/\/+$/, "")}`;
}
function fetchManifest(address) {
  const m = ON_THE_NETWORK[address];
  if (!m) throw new HttpError(422, `${UNREACHABLE(address)} (In the mockup, try http://192.168.10.216:8080.)`);
  return structuredClone(m);
}
// The script a plugin's page loads, the backend's own (served as /plugins/farmhand-plugin.js)
const SCRIPT = (() => {
  try {
    return readFileSync(new URL("../../../backend/app/services/plugins/farmhand-plugin.js", import.meta.url), "utf-8");
  } catch {
    return "window.farmhand = { inFarmhand: window.parent !== window, theme: null, onTheme() { return () => {}; } };";
  }
})();
// A pretend plugin's own page, in Farmhand's colours (farmhand-plugin.js). Hello lists the printers its own backend
// read through the plugin API (its api/printers, below); Shelf clock shows the time.
const PAGE_STYLE = `
  body { margin: 0; padding: 24px; font-family: var(--farmhand-font, system-ui, sans-serif); background: var(--farmhand-bg, #1B1D1E); color: var(--farmhand-text-primary, #F4F5F4); }
  h1 { font-size: 18px; color: var(--farmhand-heading, #fff); margin: 0 0 6px; }
  p, li { color: var(--farmhand-text-muted, #CBCED0); font-size: 14px; line-height: 1.6; }
  .box { border: 1px solid var(--farmhand-border, #3D4042); background: var(--farmhand-panel, #232527); border-radius: 4px; padding: 16px; max-width: 640px; }
  b { color: var(--farmhand-amber, #E39F3A); }`;
const HELLO_BODY = `<p>The printers it read through the plugin API:</p><ul id="printers"><li>asking…</li></ul>
<script>
  fetch("api/printers").then((r) => r.json()).then((r) => {
    document.getElementById("printers").innerHTML = r.printers.map((p) => "<li><b>" + p.name + "</b> " + p.connection_type + "</li>").join("") || "<li>none</li>";
  }).catch((e) => { document.getElementById("printers").textContent = String(e); });
</script>`;
const CLOCK_BODY = `<p>It's <b id="clock"></b> here.</p>
<script>setInterval(() => { document.getElementById("clock").textContent = new Date().toLocaleTimeString(); }, 500);</script>`;
const pageHtml = (p) => `<!doctype html><html><head><meta charset="utf-8"><title>${p.name}</title>
<script src="/plugins/farmhand-plugin.js"></script><style>${PAGE_STYLE}</style></head><body><div class="box">
<h1>${p.name}, a pretend plugin</h1>
<p>This page comes from the plugin (in the mockup, from the mock backend), shown inside Farmhand. Its colours follow Farmhand's: change them on the Appearance page and come back.</p>
${p.id === "hello" ? HELLO_BODY : CLOCK_BODY}
</div></body></html>`;
// A small page where a plugin's page would be (as services/plugins/pages.py's message_page)
const messagePage = (title, text) => `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><style>${PAGE_STYLE}</style></head>
<body><div class="box"><h1>${title}</h1><p>${text}</p></div></body></html>`;

export function pluginsRoutes(ctx) {
  const { farm, on, printer, requireConfirm, mainsailUrl, moonrakerUrl, prusalinkUrl, progressOf } = ctx;
  const now = () => new Date().toISOString();
  const newToken = (p) => Object.assign(p, { token: randomBytes(32).toString("base64url"), tokenCreatedAt: now(), tokenLastUsedAt: null, needsToken: false });
  const answered = (address) => (ON_THE_NETWORK[address]
    ? { state: "running", last_error: null, last_seen_at: now(), checked_at: now() }
    : { state: "not_answering", last_error: UNREACHABLE(address), last_seen_at: null, checked_at: now() });
  const record = (manifest, { permissions, address, onlyFrom, image = null }) => newToken({
    id: manifest.id, name: manifest.name, version: manifest.version, image, farmhand_api: manifest.farmhand_api, enabled: true,
    permissions: [...new Set(permissions)], manifest, created_at: now(), address, onlyFromAddress: onlyFrom, health: answered(address),
  });
  // Hello is added already: the sample farm's plugin (its token isn't given to anyone, it's pretend)
  const plugins = () => (farm.plugins ??= [record(checkManifest(ON_THE_NETWORK["http://192.168.10.215:8080"]), {
    permissions: ["printers:read", "prints:read", "farm:read"], address: "http://192.168.10.215:8080", onlyFrom: true,
  })]);
  const find = (id) => plugins().find((p) => p.id === id) || (() => { throw new HttpError(404, "Plugin not found"); })();
  const out = (p) => ({
    id: p.id, name: p.name, version: p.version, image: p.image, farmhand_api: p.farmhand_api, enabled: p.enabled,
    permissions: p.permissions, permissions_described: describe(p.permissions), manifest: p.manifest, created_at: p.created_at,
    address: p.address, only_from_address: p.onlyFromAddress, needs_token: !!p.needsToken, page: p.manifest.page ?? null,
    health: p.enabled ? p.health : { ...p.health, state: "off" },
    token_created_at: p.needsToken ? null : p.tokenCreatedAt, token_last_used_at: p.tokenLastUsedAt,
  });
  const checkGrant = (manifest, granted) => {
    if (!Array.isArray(granted) || !granted.every((p) => typeof p === "string")) throw new HttpError(422, "The permissions granted must be a list, like [\"printers:read\"].");
    const extra = granted.filter((p) => !manifest.permissions.includes(p));
    if (extra.length) throw new HttpError(422, `The plugin didn't ask for ${extra.map((p) => `'${p}'`).join(", ")}: only what it asks for can be granted.`);
  };
  const notTwice = (id) => {
    if (plugins().some((p) => p.id === id)) throw new HttpError(409, `A plugin called "${id}" is already installed. Remove it first to install it again.`);
  };

  // ------------------------------------------------------------------ the Plugins page
  on("GET", "/plugins", () => ({ plugins: [...plugins()].sort((a, b) => a.name.localeCompare(b.name)).map(out), api_version: API_VERSION, permissions: describe(Object.keys(PERMISSIONS)) }));
  on("POST", "/plugins/preview", (_, body) => {
    const address = tidyAddress(body.address);
    const manifest = checkManifest(fetchManifest(address));
    return { address, manifest, permissions_described: describe(manifest.permissions), installed: plugins().some((p) => p.id === manifest.id) };
  });
  on("POST", "/plugins", (_, body) => {
    let p;
    if (body.address != null) {
      const address = tidyAddress(body.address);
      const manifest = checkManifest(fetchManifest(address));
      notTwice(manifest.id);
      checkGrant(manifest, body.permissions);
      p = record(manifest, { permissions: body.permissions, address, onlyFrom: body.only_from_address !== false });
    } else if (body.manifest != null) {
      // its manifest itself: a container beside Farmhand, named by its id
      const manifest = checkManifest(body.manifest);
      notTwice(manifest.id);
      checkGrant(manifest, body.permissions);
      p = record(manifest, { permissions: body.permissions, address: `http://${manifest.id}:${manifest.port}`, onlyFrom: !!body.only_from_address, image: body.image?.trim() || null });
    } else {
      throw new HttpError(422, "Give the plugin's address, like http://192.168.10.215:8080.");
    }
    plugins().push(p);
    return [201, { plugin: out(p), token: p.token }];
  });
  on("GET", "/plugins/:id", ({ id }) => out(find(id)));
  on("PATCH", "/plugins/:id", ({ id }, body) => {
    const p = find(id);
    if (body.address != null) {
      const address = tidyAddress(body.address);
      const found = checkManifest(fetchManifest(address));
      if (found.id !== p.id) throw new HttpError(422, `The plugin at ${address} is "${found.id}", not "${p.id}". To use that one, add it as a plugin of its own.`);
      Object.assign(p, { address, health: answered(address) });
    }
    if (body.enabled != null) p.enabled = !!body.enabled;
    if (body.only_from_address != null) p.onlyFromAddress = !!body.only_from_address;
    return out(p);
  });
  on("POST", "/plugins/:id/token", ({ id }) => {
    const p = newToken(find(id));
    return { plugin: out(p), token: p.token };
  });
  on("DELETE", "/plugins/:id", ({ id }, _b, q) => {
    requireConfirm(q);
    find(id);
    farm.plugins = plugins().filter((p) => p.id !== id);
    return [204, null];
  });

  // A plugin's page, as the browser asks for it: /plugins/<id>/<path> (and /plugins/farmhand-plugin.js), answered
  // the way the API's /plugins/<id>/page/<path> does. true when it was one of these.
  const pluginPageRequest = (req, res) => {
    const url = new URL(req.url, "http://mock");
    const send = (status, body, type = "text/html; charset=utf-8") => {
      res.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store" });
      res.end(body);
      return true;
    };
    if (url.pathname === "/plugins/farmhand-plugin.js") return send(200, SCRIPT, "text/javascript");
    // /plugins/<id> without its "/" (nginx.conf does the same)
    if (/^\/plugins\/[a-z0-9-]+$/.test(url.pathname)) {
      res.writeHead(302, { Location: `${url.pathname}/${url.search}` });
      res.end();
      return true;
    }
    const m = url.pathname.match(/^\/plugins\/([a-z0-9-]+)(\/.*)$/);
    if (!m) return false;
    const p = plugins().find((x) => x.id === m[1]);
    if (!p) return send(404, messagePage("There's no such plugin", `No plugin called "${m[1]}" is added to Farmhand.`));
    if (!p.enabled) return send(403, messagePage("This plugin is switched off", `${p.name} is switched off. Switch it on on the Plugins page to use it.`));
    if (!ON_THE_NETWORK[p.address]) return send(502, messagePage("This plugin isn't running", UNREACHABLE(p.address)));
    if (m[2] === "/") return send(200, pageHtml(p));
    if (m[2] === "/api/printers") {
      const printers = farm.printers.filter((x) => !x.decommissioned).map((x) => ({ id: x.id, name: x.name, connection_type: x.prusalink ? "prusalink" : "moonraker" }));
      return send(200, JSON.stringify({ printers }), "application/json");
    }
    return send(404, "not here", "text/plain");
  };

  // ------------------------------------------------------------------ the plugin API v1
  // (the real API also takes a token only from its plugin's address when asked to, and only so often: not mirrored here)
  const caller = (headers) => {
    const [scheme, token] = (headers.authorization || "").split(" ");
    if (scheme?.toLowerCase() !== "bearer" || !token) throw new HttpError(401, NO_TOKEN);
    const p = plugins().find((x) => x.token === token && x.enabled);
    if (!p) throw new HttpError(401, BAD_TOKEN);
    p.tokenLastUsedAt = new Date().toISOString();
    return p;
  };
  const needs = (headers, permission) => {
    const p = caller(headers);
    if (!p.permissions.includes(permission)) throw new HttpError(403, `The "${p.id}" plugin hasn't been given the ${permission} permission, which this needs. Add it to the plugin's manifest; the operator grants it when installing the plugin.`);
    return p;
  };
  const active = () => farm.printers.filter((p) => !p.decommissioned).sort((a, b) => a.name.localeCompare(b.name));
  const kindOf = (p) => (p.prusalink ? "prusalink" : "moonraker");
  const api = (path) => `/plugin-api/v${API_VERSION}${path}`;

  on("GET", api("/me"), (_p, _b, _q, h) => {
    const p = caller(h);
    return { plugin_id: p.id, permissions: [...p.permissions].sort(), api_version: API_VERSION };
  });
  on("GET", api("/printers"), (_p, _b, _q, h) => {
    needs(h, "printers:read");
    return { printers: active().map((p) => ({
      id: p.id, name: p.name, kind: p.kind ?? null, connection_type: kindOf(p),
      addresses: {
        wired_ip: p.wired_ip ?? null, wireless_ip: p.wireless_ip ?? null,
        moonraker_url: p.prusalink ? null : moonrakerUrl(p), mainsail_url: p.prusalink ? null : mainsailUrl(p),
        prusalink_url: prusalinkUrl(p), camera_address: p.cameraAddress ?? null,
      },
    })) };
  });
  on("GET", api("/cameras"), (_p, _b, _q, h) => {
    needs(h, "cameras:read");
    const camera = (name, kind, url, snapshot = null) => ({
      name, kind, url, ffmpeg_input: [...(kind === "mjpeg" ? MJPEG : RTSP), "-i", url], rotation: 0, flip_horizontal: false,
      flip_vertical: false, ffmpeg_filters: [], aspect_ratio: "16:9", target_fps: 15, snapshot_url: snapshot, error: null,
    });
    return { printers: active().map((p) => {
      const base = { printer_id: p.id, printer_name: p.name };
      if (p.prusalink) {
        if (!p.cameraAddress) return { ...base, cameras: [], error: "No camera address set. Add the Buddy3D camera's IP on the printer's Edit page" };
        return { ...base, cameras: [camera("Camera", "rtsp", `rtsp://${p.cameraAddress}/live`)], error: null };
      }
      if (!p.moonraker) return { ...base, cameras: [], error: NO_MOONRAKER };
      if (!p.moonraker.reachable) return { ...base, cameras: [], error: p.moonraker.error };
      const web = mainsailUrl(p);
      return { ...base, cameras: [camera("Bed", "mjpeg", `${web}webcam/?action=stream`, `${web}webcam/?action=snapshot`)], error: null };
    }) };
  });
  on("GET", api("/printers/:id/print"), ({ id }, _b, _q, h) => {
    needs(h, "prints:read");
    return progressOf(printer(id));
  });
  // Server-sent events: the mockup's printers don't change on their own, so only the "still here" comments come
  // (and, as the real one, it ends once the token stops being taken: a new one made, switched off or removed)
  on("GET", api("/events"), (_p, _b, _q, h) => {
    const { token } = needs(h, "prints:read");
    return {
      stream(req, res) {
        res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
        res.write(": connected\n\n");
        const timer = setInterval(() => {
          if (plugins().some((x) => x.token === token && x.enabled && x.permissions.includes("prints:read"))) return res.write(": still here\n\n");
          clearInterval(timer);
          res.end(": this plugin's token is no longer taken (a new one was made, or the plugin was switched off or removed)\n\n");
        }, 15000);
        req.on("close", () => clearInterval(timer));
      },
    };
  });
  on("GET", api("/farm"), (_p, _b, _q, h) => {
    needs(h, "farm:read");
    const look = farm.config.appearance || {};
    const { colors, mode } = paletteFor(look.scheme || "farmhand", Number(look.contrast) || 0);
    if (look.file_name_color && look.file_name_color !== "auto") colors.fileName = look.file_name_color;
    return { scheme: look.scheme || "farmhand", mode, colors, time_zone: farm.config.preferences?.time_zone ?? null };
  });
  return { pluginPageRequest };
}
