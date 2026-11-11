// Plugins: programs other people write, each running in its own container (on this machine or another one on the
// farm's network), that read Farmhand through the plugin API. The Plugins page adds one by its address (after a look
// at what it asks for), switches it off or on, gives it a new token and removes it; a plugin with a page gets a menu
// entry, its page shown inside Farmhand from /plugins/<id>/. A token comes back only once, when it's made.
import { API_BASE, del, jsonBody, request } from "./client.js";

// { id, name, version, author, homepage, enabled, permissions, permissionsDescribed: [{ permission, means }], address,
// onlyFromAddress, needsToken (brought back by Load all settings: no token yet), page: { menu, icon, path } | null,
// health: { state: "running" | "not_answering" | "unknown" | "off", lastError, lastSeenAt, checkedAt }, createdAt,
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
  health: {
    state: p.health?.state || "unknown",
    lastError: p.health?.last_error || null,
    lastSeenAt: p.health?.last_seen_at || null,
    checkedAt: p.health?.checked_at || null,
  },
  createdAt: p.created_at,
  tokenCreatedAt: p.token_created_at,
  tokenLastUsedAt: p.token_last_used_at,
});

// { plugins, apiVersion, permissions: [{ permission, means }] (every one there is) }
export const getPlugins = () =>
  request("/plugins").then((r) => ({ plugins: r.plugins.map(normalizePlugin), apiVersion: r.api_version, permissions: r.permissions }));

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

// Where a plugin's page is shown from: the web server passes /plugins/<id>/ on to the plugin (nginx.conf; the
// mockup and `npm run dev` do the same)
export const pluginPageUrl = (id, path = "/") => `/plugins/${encodeURIComponent(id)}${path.startsWith("/") ? path : `/${path}`}`;

// The FARMHAND_URL a plugin is given: the plugin API as this browser reaches the API, which a plugin on another
// machine on the same network reaches the same way (one beside Farmhand in Docker can use http://api:4545/plugin-api/v1)
export const pluginApiUrl = (version = "1") => `${new URL(API_BASE, window.location.href).href.replace(/\/$/, "")}/plugin-api/v${version}`;
