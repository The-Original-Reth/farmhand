import { useEffect, useRef, useState } from "react";
import { c, look, ui } from "../theme.js";

// What a plugin's page is told of Farmhand's look (farmhand-plugin.js turns it into CSS variables)
const theme = () => ({ mode: look.mode, colors: { ...c }, font: ui.fontFamily });

// A plugin's page in an iframe: given Farmhand's colours once its farmhand-plugin.js says it's ready, and again on every
// redraw where they changed (the Appearance page); and how tall the page says it is ("farmhand:height", null until it
// says). A settings page with a Save of its own (farmhand-plugin.js onSave) says so, and whether it has changes: `saves`,
// `changed`, and save() asks it to save, resolving to what it answered ({ ok, text }). { frame (the iframe's ref),
// onLoad, height, saves, changed, save }.
export function usePluginFrame() {
  const frame = useRef(null);
  const sent = useRef("");
  const asked = useRef({}); // saves asked for and not answered yet: id -> resolve
  const [height, setHeight] = useState(null);
  const [saves, setSaves] = useState(false);
  const [changed, setChanged] = useState(false);
  const send = (force = false) => {
    const t = theme();
    const key = JSON.stringify(t);
    if (!frame.current?.contentWindow || (!force && key === sent.current)) return;
    sent.current = key;
    frame.current.contentWindow.postMessage({ type: "farmhand:theme", theme: t }, "*");
  };
  useEffect(() => {
    const heard = (e) => {
      if (e.source !== frame.current?.contentWindow) return;
      if (e.data?.type === "farmhand:ready") send(true);
      if (e.data?.type === "farmhand:height" && Number.isFinite(e.data.height)) setHeight(Math.max(40, Math.min(5000, e.data.height)));
      if (e.data?.type === "farmhand:saves") setSaves(!!e.data.saves);
      if (e.data?.type === "farmhand:changed") setChanged(!!e.data.changed);
      if (e.data?.type === "farmhand:saved" && asked.current[e.data.id]) {
        asked.current[e.data.id]({ ok: e.data.ok !== false, text: typeof e.data.text === "string" ? e.data.text.slice(0, 500) : null });
        delete asked.current[e.data.id];
      }
    };
    window.addEventListener("message", heard);
    return () => window.removeEventListener("message", heard);
  }, []);
  useEffect(() => send()); // every redraw: a new look is passed on
  const save = () =>
    new Promise((resolve) => {
      const id = `${Date.now()}-${Math.random()}`;
      asked.current[id] = resolve;
      frame.current?.contentWindow?.postMessage({ type: "farmhand:save", id }, "*");
      setTimeout(() => {
        if (!asked.current[id]) return;
        delete asked.current[id];
        resolve({ ok: false, text: "The plugin didn't answer. Is it running?" });
      }, 60000); // (connecting to a NAS can take a while)
    });
  return { frame, onLoad: () => send(true), height, saves, changed, save };
}

// What a plugin's iframe may do: everything a page needs, but never navigate Farmhand's own page away
export const PLUGIN_SANDBOX = "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals";
