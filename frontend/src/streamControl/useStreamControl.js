import { useEffect, useRef, useState } from "react";
import { errorText, getStreamControl, getStreamPlugins } from "../api.js";

const STREAMS_EVERY_MS = 5000; // how often the stream plugins are asked how they're doing (only while the page is in view)

// Stream control's page from the server (getStreamControl), loaded once and its stream plugins asked again every few
// seconds. { page (null until loaded), loadError, take(p) (a page the server answered after a change: one answered
// without the stream plugins keeps those last heard), setPage, reload() (the page read again: resolves to it) }
// A plugin can take up to 6 s to answer, so the next ask waits for the last one; and an answer asked for before a change
// here (Go live, Stop...) was answered is let go, so it can't put back how the streams were before it.
export function useStreamControlPage() {
  const [page, setPageNow] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const changes = useRef(0); // one more each time the page is changed here
  const setPage = (next) => {
    changes.current += 1;
    setPageNow(next);
  };
  const take = (p) => setPage((now) => ({ ...p, streams: p.streams ?? now?.streams ?? [], happened: p.happened ?? now?.happened ?? [] }));
  const reload = async () => {
    const p = await getStreamControl();
    take(p);
    return p;
  };

  useEffect(() => {
    let live = true;
    let asking = false;
    getStreamControl().then((p) => live && (take(p), setLoadError(null))).catch((e) => live && setLoadError(errorText(e)));
    const timer = setInterval(() => {
      if (document.hidden || asking) return;
      asking = true;
      const before = changes.current;
      getStreamPlugins()
        .then((r) => live && before === changes.current && setPageNow((now) => now && { ...now, streams: r.streams, happened: r.happened }))
        .catch(() => {})
        .finally(() => {
          asking = false;
        });
    }, STREAMS_EVERY_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  return { page, loadError, take, setPage, reload };
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
