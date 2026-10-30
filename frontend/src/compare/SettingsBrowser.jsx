import { useEffect, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { monoText, uiText } from "../styles.js";
import { errorText, fetchVersionSettings } from "../api.js";
import { boxStyle, pagesWithContent, SettingsPages, SlicerColors, slicerColors, unescape } from "../settings/fields.jsx";
import { BOSS_CHOICES, bossTabs, bossValue } from "../settings/boss.js";
import { ORCA_CHOICES, orcaTabs, orcaValue } from "../settings/orca.js";

// ---------------------------------------------------------------------------
// One 3MF version's settings, laid out the way the slicer it came from shows them, read-only: PrusaSlicer (BOSS
// edition)'s Print / Filament / Printer Settings tabs with their pages down the left, or OrcaSlicer's (and Bambu
// Studio's) Process / Filament / Printer settings with their pages across the top. Each in its slicer's own colours
// (Prusa orange, Orca teal green), dark or light to match the scheme in use.
// ---------------------------------------------------------------------------
const LAYOUTS = {
  boss: { slicer: "prusa", tabs: bossTabs, value: bossValue, choices: BOSS_CHOICES, nav: "left" },
  orca: { slicer: "orca", tabs: orcaTabs, value: orcaValue, choices: ORCA_CHOICES, nav: "top" },
};
const layoutFor = (family) => (family === "orcaslicer" || family === "bambustudio" ? LAYOUTS.orca : LAYOUTS.boss);

// Loads a version's settings, then hands them to SettingsBrowser. Kept as two
// components on purpose: SettingsBrowser has its own state hooks, and they
// must not sit after the loading/error early returns (React requires the
// same hooks in the same order on every render of a component).
export function SettingsViewer({ bundle, ver }) {
  const [settings, setSettings] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setSettings(null);
    setLoadError(null);
    fetchVersionSettings(ver.id)
      .then((s) => !cancelled && setSettings(s))
      .catch((e) => !cancelled && setLoadError(errorText(e)));
    return () => {
      cancelled = true;
    };
  }, [ver.id]);

  if (loadError) {
    return <div style={uiText(13, c.amber)}>Couldn't load settings: {loadError}</div>;
  }
  if (!settings) {
    return <div style={uiText(13, c.textFaint)}>Loading settings…</div>;
  }

  return <SettingsBrowser bundle={bundle} ver={ver} settings={settings} />;
}

function SettingsBrowser({ bundle, ver, settings }) {
  const layout = layoutFor(ver.slicerFamily);
  const value = useMemo(() => layout.value(settings), [layout, settings]);
  // the slicer's tabs, each with only the pages this file has something on
  const tabs = useMemo(
    () => layout.tabs(settings).map((t) => ({ ...t, pages: pagesWithContent(t.pages, (page) => (key) => value(key, page)) })).filter((t) => t.pages.length),
    [layout, settings, value],
  );
  const [tabId, setTabId] = useState(tabs[0]?.id);
  const tab = tabs.find((t) => t.id === tabId) || tabs[0];
  const p = slicerColors(layout.slicer);

  return (
    <SlicerColors.Provider value={p}>
    <div data-testid="slicer-window" style={{ background: p.bg, color: p.textPrimary, border: `1px solid ${p.border}`, borderRadius: 4, padding: 14 }}>
      <div style={uiText(12, p.textFaint, { marginBottom: 12 })}>
        {ver.filename || bundle.name} · v{ver.v} · {ver.slicer || "unknown slicer"} · {Object.keys(settings).length} settings
      </div>

      <div role="tablist" style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 12, borderBottom: `1px solid ${p.border}` }}>
        {tabs.map((t) => {
          const on = t.id === tab?.id;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={on}
              data-testid="settings-tab"
              onClick={() => setTabId(t.id)}
              style={{
                ...ui, fontSize: fs(13), display: "flex", alignItems: "center", gap: 7, padding: "7px 14px", marginBottom: -1,
                border: `1px solid ${on ? p.border : "transparent"}`, borderBottom: `2px solid ${on ? p.accent : "transparent"}`,
                borderRadius: "4px 4px 0 0", background: on ? p.field : "transparent", color: on ? p.heading : p.textMuted,
                fontWeight: on ? 600 : 400, cursor: "pointer",
              }}
            >
              <t.Icon size={14} color={on ? p.accentText : p.textFaint} />
              {t.title}
            </button>
          );
        })}
      </div>

      {tab && (
        <>
          {tab.preset && (
            <div style={{ marginBottom: 14 }}>
              <span data-testid="settings-preset" style={boxStyle({ ...monoText(13, p.heading), padding: "5px 10px", gap: 8, maxWidth: "100%", overflowWrap: "anywhere" }, p)}>
                <tab.Icon size={14} color={p.accentText} />
                {unescape(tab.preset).replace(/^"|"$/g, "")}
                <ChevronDown size={13} color={p.textFaint} />
              </span>
            </div>
          )}
          <SettingsPages key={tab.id} pages={tab.pages} value={value} choices={layout.choices} nav={layout.nav} label={`${tab.title} pages`} />
        </>
      )}
    </div>
    </SlicerColors.Provider>
  );
}
