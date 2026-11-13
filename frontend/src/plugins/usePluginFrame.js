import { useEffect, useRef, useState } from "react";
import { c, look, ui } from "../theme.js";

// What a plugin's page is told of Farmhand's look (farmhand-plugin.js turns it into CSS variables)
const theme = () => ({ mode: look.mode, colors: { ...c }, font: ui.fontFamily });

// A plugin's page in an iframe: given Farmhand's colours once its farmhand-plugin.js says it's ready, and again on every
// redraw where they changed (the Appearance page); and how tall the page says it is ("farmhand:height", null until it
// says). { frame (the iframe's ref), onLoad, height }.
export function usePluginFrame() {
  const frame = useRef(null);
  const sent = useRef("");
  const [height, setHeight] = useState(null);
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
    };
    window.addEventListener("message", heard);
    return () => window.removeEventListener("message", heard);
  }, []);
  useEffect(() => send()); // every redraw: a new look is passed on
  return { frame, onLoad: () => send(true), height };
}

// What a plugin's iframe may do: everything a page needs, but never navigate Farmhand's own page away
export const PLUGIN_SANDBOX = "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals";
