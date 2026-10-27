import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { errorText, fetchAll, getPrinters, normalizeBundle, normalizePrinter, normalizeSourceModel } from "./api.js";
import { searchableExtras } from "./lib/search.jsx";

const NONE = [];

const DataContext = createContext(null);

export function DataProvider({ children }) {
  const [state, setState] = useState({ printers: [], sourceModels: [], bundles: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      setState(await fetchAll());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // After a change to one printer, model or 3MF: put the server's answer for it in place (or add it), instead of
  // reloading everything. refresh() stays for uploads and deletes, which can touch several things at once.
  const put = useCallback((list, normalize) => (raw) => {
    const item = normalize(raw);
    setState((s) => {
      const items = s[list];
      const i = items.findIndex((x) => x.id === item.id);
      return { ...s, [list]: i < 0 ? [...items, item] : items.map((x, j) => (j === i ? item : x)) };
    });
    return item;
  }, []);
  const putPrinter = useMemo(() => put("printers", normalizePrinter), [put]);
  const putModel = useMemo(() => put("sourceModels", normalizeSourceModel), [put]);
  const putBundle = useMemo(() => put("bundles", normalizeBundle), [put]);
  // Just the printers (a sync moved their print hours and service on): the models and 3MFs haven't changed
  const refreshPrinters = useCallback(async () => {
    const printers = (await getPrinters()).map(normalizePrinter);
    setState((s) => ({ ...s, printers }));
  }, []);

  const value = useMemo(() => {
    const { printers, sourceModels, bundles } = state;

    // bundles <-> source models is many-to-many (a mixed plate has several). Looked up through maps made once per
    // load, not by scanning every 3MF on each call (the Models list asks for every model's on every keystroke).
    const modelById = new Map(sourceModels.map((m) => [m.id, m]));
    const byModel = new Map();
    const byPrinter = new Map();
    for (const b of bundles) {
      b.sourceModelIds.forEach((id) => (byModel.get(id) ?? byModel.set(id, []).get(id)).push(b));
      (byPrinter.get(b.printerId) ?? byPrinter.set(b.printerId, []).get(b.printerId)).push(b);
    }
    const bundlesForModel = (modelId) => byModel.get(modelId) ?? NONE;
    const modelsForBundle = (bundle) => bundle.sourceModelIds.map((id) => modelById.get(id)).filter(Boolean);
    const bundlesForPrinter = (printerId) => byPrinter.get(printerId) ?? NONE;
    const modelsForPrinter = (printerId) => {
      const ids = new Set();
      bundlesForPrinter(printerId).forEach((b) => b.sourceModelIds.forEach((id) => ids.add(id)));
      return [...ids].map((id) => modelById.get(id)).filter(Boolean);
    };
    // What each model can be searched by besides its name (its 3MF files, printers, slicer, notes), lowercased once
    const searchIndex = new Map(sourceModels.map((m) => [m.id, searchableExtras(m, bundlesForModel(m.id), printers)]));
    const bundleTitle = (bundle) =>
      modelsForBundle(bundle).map((m) => m.name).join("  +  ");
    const compareLabel = (bundle) => {
      const printer = printers.find((p) => p.id === bundle.printerId);
      const shortNames = modelsForBundle(bundle)
        .map((m) => m.name.replace(/\.(stl|obj|step|stp)$/i, ""))
        .join(" + ");
      return `${printer?.name ?? "?"} · ${shortNames}`;
    };

    // Compare picks individual VERSIONS (v1 and v2 of the same 3MF, or any two anywhere), so look them up by id
    const versionIndex = {};
    bundles.forEach((b) => b.versions.forEach((v) => (versionIndex[v.id] = { bundle: b, version: v })));
    const versionLabel = (entry) => `${compareLabel(entry.bundle)} · v${entry.version.v}`;

    const versionsByBundle = Object.fromEntries(bundles.map((b) => [b.id, b.versions]));
    const sourceVersionsByModel = Object.fromEntries(sourceModels.map((m) => [m.id, m.versions]));

    return {
      printers,
      sourceModels,
      bundles,
      versionsByBundle,
      sourceVersionsByModel,
      bundlesForModel,
      modelsForBundle,
      bundlesForPrinter,
      modelsForPrinter,
      bundleTitle,
      compareLabel,
      versionIndex,
      versionLabel,
      searchIndex,
      refresh,
      refreshPrinters,
      putPrinter,
      putModel,
      putBundle,
      loading,
      error,
    };
  }, [state, refresh, refreshPrinters, putPrinter, putModel, putBundle, loading, error]);

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

export const useData = () => {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used inside <DataProvider>");
  return ctx;
};
