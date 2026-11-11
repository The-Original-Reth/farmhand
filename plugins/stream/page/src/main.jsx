import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/play/400.css"; // the Play font, bundled so it works with no internet
import "@fontsource/play/700.css";
import { c, look, ui } from "./theme.js";
import { errorText, getLayouts, saveLayouts } from "./api.js";
import { FarmProvider, useData } from "./data.jsx";
import { PluginPanel } from "./PluginPanel.jsx";
import { StreamSection } from "./stream/StreamSection.jsx";
import { YouTubeGuide } from "./stream/YouTubeGuide.jsx";
import { YouTubeSettingsWindow } from "./stream/YouTubeSettings.jsx";

// The Stream plugin's page: Farmhand's Stream page, served by the plugin and shown inside Farmhand at /plugins/stream/.
// It takes Farmhand's colours and font through Farmhand's helper (farmhand-plugin.js), changing the theme in place as
// Farmhand's own pages do (theme.js), and draws again when they change. Pages of their own, opened in a new tab or
// window: ?view=youtube-guide (connecting to a YouTube channel) and ?view=youtube-settings.

function useFarmhandTheme() {
  const [, setDrawn] = useState(0);
  useEffect(() => {
    const fh = window.farmhand;
    if (!fh?.onTheme) return undefined;
    return fh.onTheme((theme) => {
      Object.assign(c, theme.colors || {});
      if (theme.font) ui.fontFamily = theme.font;
      look.mode = theme.mode === "light" ? "light" : "dark";
      setDrawn((n) => n + 1);
    });
  }, []);
  useEffect(() => {
    document.body.style.margin = "0";
    document.body.style.background = c.bg;
  });
}

function StreamPage() {
  const { farmhandError } = useData();
  const [layouts, setLayouts] = useState([]);
  const [problem, setProblem] = useState(null);
  const reload = () => getLayouts().then(setLayouts).catch((e) => setProblem(errorText(e)));
  useEffect(() => {
    reload();
  }, []);
  const onSaveLayouts = async (list) => setLayouts(await saveLayouts(list));
  return (
    <div style={{ padding: 16 }}>
      {problem && <div style={{ ...ui, color: c.danger, fontSize: 13, marginBottom: 10 }}>Couldn't load the saved layouts: {problem}</div>}
      <StreamSection
        layouts={layouts} onSaveLayouts={onSaveLayouts} onSlideshowRenamed={reload}
        aside={(page) => <PluginPanel page={page} farmhandError={farmhandError} onMigrated={() => window.location.reload()} />}
      />
    </div>
  );
}

function Root() {
  useFarmhandTheme();
  const view = new URLSearchParams(window.location.search).get("view");
  if (view === "youtube-guide") return <YouTubeGuide />;
  if (view === "youtube-settings") return <YouTubeSettingsWindow />;
  return (
    <FarmProvider>
      <StreamPage />
    </FarmProvider>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
