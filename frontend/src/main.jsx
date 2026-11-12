import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/play/400.css"; // the Play font, bundled with the app so it works with no internet
import "@fontsource/play/700.css";
import App from "./App.jsx";
import { loadAppearance, applyAppearance } from "./appearance.js";

applyAppearance(loadAppearance()); // before the first render, so the saved look never flashes the default one

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
