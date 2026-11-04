import { useEffect, useState } from "react";
import { c, fs, ui } from "../theme.js";
import { getConfig } from "../api.js";
import { AppearanceSection } from "../AppearanceSection.jsx";

// The breadcrumb above each page (Printers / BOG / Frog.3mf): every step but the last goes back to it
export function Crumb({ items, onJump }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      {items.map((it, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {i > 0 && <span style={{ color: c.textFaint }}>/</span>}
          <button
            onClick={() => onJump(i)}
            disabled={i === items.length - 1}
            style={{
              ...ui,
              background: "none",
              border: "none",
              padding: 0,
              fontSize: fs(14),
              cursor: i === items.length - 1 ? "default" : "pointer",
              color: i === items.length - 1 ? c.heading : c.textMuted,
              fontWeight: i === items.length - 1 ? 600 : 400,
            }}
          >
            {it}
          </button>
        </div>
      ))}
    </div>
  );
}

// A whole page saying something went wrong (the API can't be reached, or drawing a page failed), with one button
export function FullPageMessage({ children, action, onAction }) {
  return (
    <div style={{ ...ui, display: "flex", flexDirection: "column", gap: 12, alignItems: "center", justifyContent: "center", height: "100vh", background: c.bg, color: c.amber, padding: 24, textAlign: "center" }}>
      {children}
      <button
        onClick={onAction}
        style={{ ...ui, fontSize: fs(13), background: c.amberDim, color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 4, padding: "7px 14px", cursor: "pointer" }}
      >
        {action}
      </button>
    </div>
  );
}

// The whole page while Farmhand's first answer from the API is on its way
export function LoadingPage() {
  return (
    <div style={{ ...ui, display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: c.bg, color: c.textFaint }}>
      Loading Farmhand…
    </div>
  );
}

// Appearance has its own page (the last menu item). It only needs to know whether a settings folder is
// chosen, to say where a change was kept.
export function AppearancePage({ appearance, saved, onChange, onSave, onDiscard, saveState }) {
  const [locationPath, setLocationPath] = useState(null);
  const refresh = () =>
    getConfig()
      .then((r) => setLocationPath(r.location.isSet ? r.location.path : null))
      .catch(() => {});
  useEffect(() => {
    refresh();
  }, []);
  useEffect(() => {
    if (saveState?.phase === "saved") refresh();
  }, [saveState]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 820 }}>
      <AppearanceSection
        appearance={appearance}
        saved={saved}
        onChange={onChange}
        onSave={onSave}
        onDiscard={onDiscard}
        saveState={saveState}
        locationPath={locationPath}
      />
    </div>
  );
}
