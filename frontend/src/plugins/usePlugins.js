import { useCallback, useEffect, useState } from "react";
import { getPlugins } from "../api.js";

const EVERY_MS = 30000; // as often as Farmhand asks each plugin whether it's well

// The plugins added to Farmhand, for the menu (a page each) and the Plugins page: asked for at the start and every
// 30 seconds, and again with refresh() after a change. `loaded` once the first answer came (or failed).
export function usePlugins() {
  const [plugins, setPlugins] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const refresh = useCallback(
    () =>
      getPlugins()
        .then((r) => setPlugins(r.plugins))
        .catch(() => {}) // an API from before plugins, or one that's away: no plugin pages, nothing else changes
        .finally(() => setLoaded(true)),
    []
  );
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, EVERY_MS);
    return () => clearInterval(timer);
  }, [refresh]);
  // the plugins with a page in the menu: switched on, with a page in their manifest
  const withPages = plugins.filter((p) => p.enabled && p.page);
  return { plugins, withPages, loaded, refresh };
}
