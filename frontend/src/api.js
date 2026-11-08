// The API client, by area (src/api/): every call the UI makes, and the API's answers turned into the shapes the
// components use. Import from here; each area's file says what it covers.
export { API_BASE, errorText } from "./api/client.js"; // the rest of the client is the area files' own
export * from "./api/printers.js";
export * from "./api/library.js";
export * from "./api/projects.js";
export * from "./api/farmCost.js";
export * from "./api/storage.js";
export * from "./api/settings.js";
export * from "./api/all.js";
