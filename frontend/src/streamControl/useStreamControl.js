import { useEffect, useState } from "react";
import { errorText, getStreamControl, getStreamPlugins } from "../api.js";

const STREAMS_EVERY_MS = 5000; // how often the stream plugins are asked how they're doing (only while the page is in view)

// Stream control's page from the server (getStreamControl), loaded once and its stream plugins asked again every few
// seconds. { page (null until loaded), loadError, take(p) (a page the server answered after a change: one answered
// without the stream plugins keeps those last heard), setPage }
export function useStreamControlPage() {
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const take = (p) => setPage((now) => ({ ...p, streams: p.streams ?? now?.streams ?? [], happened: p.happened ?? now?.happened ?? [] }));

  useEffect(() => {
    let live = true;
    getStreamControl().then((p) => live && (take(p), setLoadError(null))).catch((e) => live && setLoadError(errorText(e)));
    const timer = setInterval(() => {
      if (document.hidden) return;
      getStreamPlugins()
        .then((r) => live && setPage((now) => now && { ...now, streams: r.streams, happened: r.happened }))
        .catch(() => {});
    }, STREAMS_EVERY_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  return { page, loadError, take, setPage };
}

// An on/off kept in this browser under `key` (Mute, Autoplay music): [on, turn(on)]. A browser that keeps nothing:
// off at first, and kept for this visit only.
export function useStoredSwitch(key) {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(key) === "1";
    } catch {
      return false;
    }
  });
  const turn = (next) => {
    setOn(next);
    try {
      localStorage.setItem(key, next ? "1" : "0");
    } catch {
      // (kept for this visit only)
    }
  };
  return [on, turn];
}
