import { useEffect, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { monoText, uiText } from "../styles.js";
import { errorText, fetchVersionSettings } from "../api.js";
import { boxStyle, DiffMarks, pagesWithContent, SettingsPages, SlicerColors, slicerColors, unescape } from "../settings/fields.jsx";
import { BOSS_CHOICES, bossTabs, bossValue } from "../settings/boss.js";
import { ORCA_CHOICES, orcaTabs, orcaValue } from "../settings/orca.js";

// ---------------------------------------------------------------------------
// One 3MF version's settings, laid out the way the slicer it came from shows them, read-only: PrusaSlicer (BOSS
// edition)'s Print / Filament / Printer Settings tabs with their pages down the left, or OrcaSlicer's (and Bambu
// Studio's) Process / Filament / Printer settings with their pages across the top. Each in its slicer's own colours
// (Prusa orange, Orca teal green), dark or light to match the scheme in use.
// ---------------------------------------------------------------------------
const LAYOUTS = {
  boss: { id: "boss", slicer: "prusa", tabs: bossTabs, value: bossValue, choices: BOSS_CHOICES, nav: "left" },
  orca: { id: "orca", slicer: "orca", tabs: orcaTabs, value: orcaValue, choices: ORCA_CHOICES, nav: "top" },
};
export const layoutFor = (family) => (family === "orcaslicer" || family === "bambustudio" ? LAYOUTS.orca : LAYOUTS.boss);

// A slicer's tabs for these settings, each with only the pages `hasFor(page)` finds something on
export const slicerTabs = (layout, settings, hasFor) =>
  layout.tabs(settings).map((t) => ({ ...t, pages: pagesWithContent(t.pages, hasFor) })).filter((t) => t.pages.length);

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
  const tabs = useMemo(() => slicerTabs(layout, settings, (page) => (key) => value(key, page) !== undefined), [layout, settings, value]);
  const [tabId, setTabId] = useState(tabs[0]?.id);
  return (
    <SlicerWindow
      layout={layout} tabs={tabs} settings={settings} value={value} tabId={tabId} onTab={setTabId}
      title={`${ver.filename || bundle.name} · v${ver.v} · ${ver.slicer || "unknown slicer"} · ${Object.keys(settings).length} settings`}
    />
  );
}

// The slicer's window: its tabs, the tab's preset, and its pages. In a comparison two of these sit side by side,
// turning together (`tabId` / `onTab`, `pageId` / `onPage`), and `compare` = { side, keys (the settings that differ),
// has (rows either file has), diffsOn (differences on a page), scroll (to scroll with the other side) } marks what differs.
export function SlicerWindow({ layout, tabs, settings, value, title, tabId, onTab, pageId, onPage, compare }) {
  const tab = tabs.find((t) => t.id === tabId) || tabs[0];
  const p = slicerColors(layout.slicer);
  const preset = tab?.presetKey && settings[tab.presetKey] ? unescape(settings[tab.presetKey]).replace(/^"|"$/g, "") : "";

  return (
    <SlicerColors.Provider value={p}>
      <DiffMarks.Provider value={compare ? { side: compare.side, keys: compare.keys } : null}>
        <div data-testid="slicer-window" style={{ background: p.bg, color: p.textPrimary, border: `1px solid ${p.border}`, borderRadius: 4, padding: 14, minWidth: 0 }}>
          <div style={uiText(12, p.textFaint, { marginBottom: 12, overflowWrap: "anywhere" })}>{title}</div>

          <div role="tablist" style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 12, borderBottom: `1px solid ${p.border}` }}>
            {tabs.map((t) => {
              const on = t.id === tab?.id;
              return (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={on}
                  data-testid="settings-tab"
                  onClick={() => onTab(t.id)}
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
              {preset && (
                <div style={{ marginBottom: 14 }}>
                  <span data-testid="settings-preset" style={boxStyle({ ...monoText(13, p.heading), padding: "5px 10px", gap: 8, maxWidth: "100%", overflowWrap: "anywhere" }, p)}>
                    <tab.Icon size={14} color={p.accentText} />
                    {preset}
                    <ChevronDown size={13} color={p.textFaint} />
                  </span>
                </div>
              )}
              <SettingsPages
                key={tab.id} pages={tab.pages} value={value} choices={layout.choices} nav={layout.nav} label={`${tab.title} pages`}
                pageId={pageId} onPage={onPage} has={compare?.has} diffsOn={compare?.diffsOn} scroll={compare?.scroll}
              />
            </>
          )}
        </div>
      </DiffMarks.Provider>
    </SlicerColors.Provider>
  );
}
