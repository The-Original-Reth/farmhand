// Writes the colour schemes (src/palettes.js) where the backend reads them for plugins (GET /plugin-api/v1/farm):
// backend/app/services/plugins/palettes.json. Run after changing a scheme:  npm run export:palettes
// (npm run check:themes fails while the backend's copy is out of date.)
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { PRESETS } from "../src/palettes.js";

export const PALETTES_JSON = new URL("../../backend/app/services/plugins/palettes.json", import.meta.url);

export const palettesJson = () =>
  JSON.stringify(Object.fromEntries(PRESETS.map((p) => [p.id, { name: p.name, mode: p.mode, colors: p.colors }])), null, 2) + "\n";

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  writeFileSync(PALETTES_JSON, palettesJson());
  console.log("Wrote backend/app/services/plugins/palettes.json");
}
