// Plugins: installing one from its manifest (/plugins, for the operator) and the plugin API v1 a plugin's container
// reads Farmhand through (/plugin-api/v1/, token- and permission-checked), in the real API's shapes
// (backend/app/routers/plugins.py, plugin_api.py; docs/plugins.md). Tokens are kept in memory by their value here;
// the real backend keeps only their hash.
import { randomBytes } from "node:crypto";
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

export function pluginsRoutes(ctx) {
  const { farm, on, printer, requireConfirm, mainsailUrl, moonrakerUrl, prusalinkUrl, progressOf } = ctx;
  const plugins = () => (farm.plugins ??= []); // [{ ...plugin, token, tokenCreatedAt, tokenLastUsedAt }]
  const find = (id) => plugins().find((p) => p.id === id) || (() => { throw new HttpError(404, "Plugin not found"); })();
  const newToken = (p) => Object.assign(p, { token: randomBytes(32).toString("base64url"), tokenCreatedAt: new Date().toISOString(), tokenLastUsedAt: null });
  const out = (p) => ({
    id: p.id, name: p.name, version: p.version, image: p.image, farmhand_api: p.farmhand_api, enabled: p.enabled,
    permissions: p.permissions, permissions_described: describe(p.permissions), manifest: p.manifest, created_at: p.created_at,
    token_created_at: p.tokenCreatedAt, token_last_used_at: p.tokenLastUsedAt,
  });

  // ------------------------------------------------------------------ installing, for the operator
  on("GET", "/plugins", () => ({ plugins: [...plugins()].sort((a, b) => a.name.localeCompare(b.name)).map(out), api_version: API_VERSION, permissions: describe(Object.keys(PERMISSIONS)) }));
  on("POST", "/plugins", (_, body) => {
    const manifest = checkManifest(body.manifest);
    const granted = body.permissions;
    if (!Array.isArray(granted) || !granted.every((p) => typeof p === "string")) throw new HttpError(422, "The permissions granted must be a list, like [\"printers:read\"].");
    const extra = granted.filter((p) => !manifest.permissions.includes(p));
    if (extra.length) throw new HttpError(422, `The plugin didn't ask for ${extra.map((p) => `'${p}'`).join(", ")}: only what it asks for can be granted.`);
    if (plugins().some((p) => p.id === manifest.id)) throw new HttpError(409, `A plugin called "${manifest.id}" is already installed. Remove it first to install it again.`);
    const p = newToken({
      id: manifest.id, name: manifest.name, version: manifest.version, image: body.image?.trim() || null, farmhand_api: manifest.farmhand_api,
      enabled: true, permissions: [...new Set(granted)], manifest, created_at: new Date().toISOString(),
    });
    plugins().push(p);
    return [201, { plugin: out(p), token: p.token }];
  });
  on("GET", "/plugins/:id", ({ id }) => out(find(id)));
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

  // ------------------------------------------------------------------ the plugin API v1
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
  on("GET", api("/events"), (_p, _b, _q, h) => {
    needs(h, "prints:read");
    return {
      stream(req, res) {
        res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
        res.write(": connected\n\n");
        const timer = setInterval(() => res.write(": still here\n\n"), 15000);
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
  return {};
}
