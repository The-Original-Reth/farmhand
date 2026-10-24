import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { fetchAll } from "./api.js";

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
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value = useMemo(() => {
    const { printers, sourceModels, bundles } = state;

    // bundles <-> source models is many-to-many (a mixed plate has several)
    const bundlesForModel = (modelId) => bundles.filter((b) => b.sourceModelIds.includes(modelId));
    const modelsForBundle = (bundle) =>
      bundle.sourceModelIds.map((id) => sourceModels.find((m) => m.id === id)).filter(Boolean);
    const bundlesForPrinter = (printerId) => bundles.filter((b) => b.printerId === printerId);
    const modelsForPrinter = (printerId) => {
      const ids = new Set();
      bundlesForPrinter(printerId).forEach((b) => b.sourceModelIds.forEach((id) => ids.add(id)));
      return [...ids].map((id) => sourceModels.find((m) => m.id === id)).filter(Boolean);
    };
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
      refresh,
      loading,
      error,
    };
  }, [state, refresh, loading, error]);

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

export const useData = () => {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used inside <DataProvider>");
  return ctx;
};
