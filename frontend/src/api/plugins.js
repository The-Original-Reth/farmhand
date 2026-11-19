// Plugins: programs other people write, each running in its own container (on this machine or another one on the
// farm's network), that read Farmhand through the plugin API. The Plugins page adds one by its address (after a look
// at what it asks for), switches it off or on, gives it a new token and removes it; a plugin with a page gets a menu
// entry, its page shown inside Farmhand from /plugins/<id>/. A token comes back only once, when it's made.
import { API_BASE, del, jsonBody, request } from "./client.js";

// { id, name, version, author, homepage, enabled, permissions, permissionsDescribed: [{ permission, means }], address,
// onlyFromAddress, needsToken (brought back by Load all settings: no token yet), page: { menu, icon, path } | null, settingsPage,
// health: { state: "running" | "unwell" | "not_answering" | "unknown" | "off", lastError, lastSeenAt, checkedAt }, createdAt,
// tokenCreatedAt, tokenLastUsedAt }
const normalizePlugin = (p) => ({
  id: p.id,
  name: p.name,
  version: p.version,
  author: p.manifest?.author || null,
  homepage: p.manifest?.homepage || null,
  enabled: p.enabled,
  permissions: p.permissions,
  permissionsDescribed: p.permissions_described,
  address: p.address,
  onlyFromAddress: p.only_from_address,
  needsToken: !!p.needs_token,
  page: p.page || null,
  settingsPage: p.manifest?.settings_page || null, // its settings, shown under its name on the Settings page
  health: {
    state: p.health?.state || "unknown",
    lastError: p.health?.last_error || null,
    lastSeenAt: p.health?.last_seen_at || null,
    checkedAt: p.health?.checked_at || null,
  },
  createdAt: p.created_at,
  tokenCreatedAt: p.token_created_at,
  tokenLastUsedAt: p.token_last_used_at,
  // what its newer manifest asks for that it hasn't been given: [{ permission, means }] (Allow on its card), or []
  asks: p.asks || [],
  // the copy of its own settings Farmhand keeps: { savedAt, receivedAt, size }, or null; canRestore: it can take it back
  backup: p.backup ? { savedAt: p.backup.saved_at, receivedAt: p.backup.received_at, size: p.backup.size } : null,
  canRestore: !!p.can_restore,
});

// A plugin built into Farmhand (Stream control): { id, name, builtin: true, enabled, description, page: { menu, icon, path } }.
// It's switched on or off with changePlugin(id, { enabled }) (answering this shape); never added, removed or given a token.
export const normalizeBuiltinPlugin = (p) => ({ id: p.id, name: p.name, builtin: true, enabled: !!p.enabled, description: p.description, page: p.page });

// { plugins, builtin (the plugins built into Farmhand), apiVersion, permissions: [{ permission, means }] (every one there is) }
export const getPlugins = () =>
  request("/plugins").then((r) => ({
    plugins: r.plugins.map(normalizePlugin), builtin: (r.builtin || []).map(normalizeBuiltinPlugin), apiVersion: r.api_version, permissions: r.permissions,
  }));

// Switch a plugin built into Farmhand on or off: its new state
export const switchBuiltinPlugin = (id, enabled) =>
  request(`/plugins/${encodeURIComponent(id)}`, jsonBody("PATCH", { enabled })).then(normalizeBuiltinPlugin);

// The plugin at an address, before it's added: { address (tidied), manifest, permissionsDescribed, installed }
export const previewPlugin = (address) =>
  request("/plugins/preview", jsonBody("POST", { address })).then((r) => ({
    address: r.address, manifest: r.manifest, permissionsDescribed: r.permissions_described, installed: r.installed,
  }));

// Add it: { plugin, token } (the token shown once)
export const addPlugin = ({ address, permissions, onlyFromAddress }) =>
  request("/plugins", jsonBody("POST", { address, permissions, only_from_address: onlyFromAddress }))
    .then((r) => ({ plugin: normalizePlugin(r.plugin), token: r.token }));

// { enabled?, onlyFromAddress?, address? }
export const changePlugin = (id, { enabled, onlyFromAddress, address }) =>
  request(`/plugins/${encodeURIComponent(id)}`, jsonBody("PATCH", { enabled, only_from_address: onlyFromAddress, address }))
    .then(normalizePlugin);

export const newPluginToken = (id) =>
  request(`/plugins/${encodeURIComponent(id)}/token`, { method: "POST" })
    .then((r) => ({ plugin: normalizePlugin(r.plugin), token: r.token }));

export const removePlugin = (id) => del(`/plugins/${encodeURIComponent(id)}`);

// Grant what the plugin's newer manifest asks for (its `asks`): its token keeps working. Answers the plugin.
export const allowPlugin = (id) => request(`/plugins/${encodeURIComponent(id)}/allow`, { method: "POST" }).then(normalizePlugin);

// Give the plugin back the copy of its own settings Farmhand keeps (its settings are replaced by it):
// { restored, savedAt, note (the plugin's own words: when they take effect) }
export const restorePluginSettings = (id) =>
  request(`/plugins/${encodeURIComponent(id)}/backup/restore?confirm=true`, { method: "POST" })
    .then((r) => ({ restored: !!r.restored, savedAt: r.saved_at || null, note: r.note || null }));

// Where a plugin's page is shown from: the web server passes /plugins/<id>/ on to the plugin (nginx.conf; the
// mockup and `npm run dev` do the same)
export const pluginPageUrl = (id, path = "/") => `/plugins/${encodeURIComponent(id)}${path.startsWith("/") ? path : `/${path}`}`;

// The FARMHAND_URL a plugin is given: the plugin API as this browser reaches the API, which a plugin on another
// machine on the same network reaches the same way (one beside Farmhand in Docker can use http://api:4545/plugin-api/v1)
export const pluginApiUrl = (version = "1") => `${new URL(API_BASE, window.location.href).href.replace(/\/$/, "")}/plugin-api/v${version}`;
