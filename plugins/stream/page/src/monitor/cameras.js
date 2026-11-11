import { useEffect, useState } from "react";
import { errorText, getPrintProgress, getWebcams } from "../api.js";
import { readStoredObject, writeStored } from "../lib/storage.js";

// Finding every printer's cameras for Monitor. Each printer's cameras show as soon as it answers, so one that's off
// doesn't hold up the rest. This browser remembers the cameras each printer had last time, and those start connecting
// straight away while the printers are asked again.
const CAMERAS_KEY = "farmhand.monitorCameras"; // each printer's cameras as it last gave them: { printer id: webcams }

// The cameras remembered from last time, as printer id -> { webcams, error, kept: true } (kept: not asked yet this time)
function rememberedCameras() {
  const kept = Object.entries(readStoredObject(CAMERAS_KEY)).filter(([, webcams]) => Array.isArray(webcams));
  return Object.fromEntries(kept.map(([id, webcams]) => [id, { webcams, error: null, kept: true }]));
}

// Keep a printer's cameras for next time, or forget them (null) when it couldn't be asked
function rememberCameras(printerId, webcams) {
  const { [printerId]: _, ...others } = readStoredObject(CAMERAS_KEY);
  writeStored(CAMERAS_KEY, webcams ? { ...others, [printerId]: webcams } : others);
}

// The cameras of `printers`: { cams, round, resyncing, resync }. cams: printer id -> { webcams, error, board, kept? }.
// resync asks every printer again; round counts the resyncs, so the tiles can start over and connect anew.
export function usePrinterCameras(printers) {
  const [cams, setCams] = useState(rememberedCameras);
  const [round, setRound] = useState(0);
  const [resyncing, setResyncing] = useState(false);
  const ids = printers.map((p) => p.id).join(",");

  // every printer is asked at once, and each one's cameras show as soon as it answers
  useEffect(() => {
    let live = true;
    let left = printers.length;
    if (!left) setResyncing(false);
    for (const p of printers) {
      getWebcams(p.id)
        .catch((e) => ({ webcams: [], error: errorText(e) }))
        .then((d) => {
          if (!live) return;
          setCams((now) => {
            // the same cameras as before keep their old objects, so none of them starts over
            const before = now[p.id]?.webcams;
            const same = before && JSON.stringify(before) === JSON.stringify(d.webcams);
            return { ...now, [p.id]: { webcams: same ? before : d.webcams, error: d.error, board: d.board || null } };
          });
          rememberCameras(p.id, d.error ? null : d.webcams);
          if (--left === 0) setResyncing(false);
        });
    }
    return () => {
      live = false;
    };
  }, [ids, round]);

  const resync = () => {
    setResyncing(true);
    setRound((r) => r + 1);
  };
  return { cams, round, resyncing, resync };
}

const PROGRESS_EVERY_MS = 5000; // how often the prints' progress is asked again (only while the page is in view)

// How far along each of `printerIds`' prints is: printer id -> { state: "printing" | "paused", progress, file } for
// the ones printing now. Asked straight away, every 5 seconds after that, and again as soon as the page comes back
// into view. A printer still answering the last ask isn't asked again; one that can't be asked just shows nothing.
// `keepErrors`: a printer that couldn't be asked is { error } instead of nothing (the Stream page says so on its camera).
export function usePrintProgress(printerIds, { keepErrors = false } = {}) {
  const [progress, setProgress] = useState({});
  const ids = printerIds.join(",");
  useEffect(() => {
    let live = true;
    const asking = new Set(); // printers whose last ask hasn't been answered yet
    const ask = () => {
      if (document.hidden) return;
      for (const id of printerIds) {
        if (asking.has(id)) continue;
        asking.add(id);
        getPrintProgress(id)
          .catch((e) => ({ error: e?.message || "No answer" }))
          .then((p) => {
            asking.delete(id);
            const kept = p?.state ? p : keepErrors && p?.error ? { error: p.error } : null;
            if (live) setProgress((now) => ({ ...now, [id]: kept }));
          });
      }
    };
    ask();
    const timer = setInterval(ask, PROGRESS_EVERY_MS);
    document.addEventListener("visibilitychange", ask);
    return () => {
      live = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", ask);
    };
  }, [ids]);
  return progress;
}
