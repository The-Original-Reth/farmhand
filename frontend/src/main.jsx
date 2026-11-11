import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/play/400.css"; // the Play font, bundled with the app so it works with no internet
import "@fontsource/play/700.css";
import App from "./App.jsx";
import { YouTubeGuide } from "./stream/YouTubeGuide.jsx";
import { WINDOW_PATH, YouTubeSettingsWindow } from "./stream/YouTubeSettings.jsx";
import { loadAppearance, applyAppearance } from "./appearance.js";

applyAppearance(loadAppearance()); // before the first render, so the saved look never flashes the default one

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    {/* pages of their own, opened in a new tab or window: connecting Farmhand to a YouTube channel, and YouTube settings */}
    {{ "/help/youtube": <YouTubeGuide />, [WINDOW_PATH]: <YouTubeSettingsWindow /> }[window.location.pathname.replace(/\/+$/, "")] || <App />}
  </React.StrictMode>
);
