// Everything the app shows on first load, in one go.
import { request } from "./client.js";
import { normalizeBundle, normalizeSourceModel } from "./library.js";
import { getPrinters, normalizePrinter } from "./printers.js";
import { normalizeProject } from "./projects.js";

export const fetchAll = async () => {
  const [printers, models, bundles, projects] = await Promise.all([
    getPrinters(),
    request("/source-models"),
    request("/bundles"),
    request("/projects"),
  ]);
  return {
    printers: printers.map(normalizePrinter),
    sourceModels: models.map(normalizeSourceModel),
    bundles: bundles.map(normalizeBundle),
    projects: projects.map(normalizeProject),
  };
};
