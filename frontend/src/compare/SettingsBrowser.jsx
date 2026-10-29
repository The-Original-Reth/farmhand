import { useEffect, useMemo, useState } from "react";
import { c, fs, ui } from "../theme.js";
import { monoText, uiText } from "../styles.js";
import { classifyPrusa, humanizeLabel, PRUSA_SECTIONS } from "../settingsLayout.js";
import { errorText, fetchVersionSettings } from "../api.js";

// ---------------------------------------------------------------------------
// Small building blocks
// ---------------------------------------------------------------------------
// A settings value that's too long for its cell — click to expand in place,
// click again to collapse. Only becomes interactive when the value actually
// overflows the truncation threshold; short values render as plain text.
function ExpandableValue({ raw }) {
  const [expanded, setExpanded] = useState(false);
  const isEmpty = raw === undefined || raw === null || raw === "";
  const full = isEmpty ? "—" : String(raw);
  const overflows = full.length > 70;
  const display = !overflows || expanded ? full : full.slice(0, 70) + "…";

  return (
    <div
      onClick={() => overflows && setExpanded((v) => !v)}
      title={overflows ? (expanded ? "Click to collapse" : "Click to expand") : undefined}
      style={monoText(12, c.textPrimary, { wordBreak: "break-word", whiteSpace: expanded ? "pre-wrap" : "normal", cursor: overflows ? "pointer" : "default" })}
    >
      {display}
      {overflows && (
        <span style={{ marginLeft: 6, color: c.teal, fontSize: fs(11), ...ui }}>
          {expanded ? "▲ less" : "▼ more"}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single-file settings viewer — read-only, styled after PrusaSlicer 2.9's own
// Print / Filament / Printer Settings tabs and their left-hand sub-pages.
// Values are plain text, never inputs, per the archive's core read-only rule.
// ---------------------------------------------------------------------------
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
  // every setting sorted into its tab and section: once per version, not on every tab or section click
  const grouped = useMemo(() => {
    const out = {};
    Object.keys(settings).forEach((key) => {
      const { tab, section } = classifyPrusa(key);
      out[tab] = out[tab] || {};
      out[tab][section] = out[tab][section] || [];
      out[tab][section].push(key);
    });
    Object.values(out).forEach((sections) => {
      Object.values(sections).forEach((list) => list.sort());
    });
    return out;
  }, [settings]);

  const tabsWithContent = Object.keys(PRUSA_SECTIONS).filter((t) => grouped[t]);
  const [activeTab, setActiveTab] = useState(tabsWithContent[0] || "Print Settings");
  const currentSections = (PRUSA_SECTIONS[activeTab] || []).filter((s) => grouped[activeTab]?.[s]?.length);
  const [activeSection, setActiveSection] = useState(currentSections[0]);
  const effectiveSection = currentSections.includes(activeSection) ? activeSection : currentSections[0];
  const rows = grouped[activeTab]?.[effectiveSection] || [];

  return (
    <div>
      <div style={uiText(12, c.textFaint, { marginBottom: 12 })}>
        {ver.filename || bundle.name} · v{ver.v} · {Object.keys(settings).length} settings
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 12, borderBottom: `1px solid ${c.border}`, paddingBottom: 12 }}>
        {Object.keys(PRUSA_SECTIONS).map((tab) => {
          const has = !!grouped[tab];
          return (
            <button
              key={tab}
              disabled={!has}
              onClick={() => {
                setActiveTab(tab);
                setActiveSection(undefined);
              }}
              style={{
                ...ui,
                fontSize: fs(13),
                padding: "7px 14px",
                borderRadius: 4,
                cursor: has ? "pointer" : "default",
                border: `1px solid ${activeTab === tab ? c.amber : c.border}`,
                background: activeTab === tab ? c.amberDim : "transparent",
                color: !has ? c.textFaint : activeTab === tab ? c.amber : c.textMuted,
                fontWeight: activeTab === tab ? 600 : 400,
              }}
            >
              {tab}
            </button>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ width: 170, flexShrink: 0, display: "flex", flexDirection: "column", gap: 2 }}>
          {currentSections.map((section) => (
            <button
              key={section}
              onClick={() => setActiveSection(section)}
              style={{
                ...ui,
                fontSize: fs(13),
                textAlign: "left",
                padding: "7px 10px",
                borderRadius: 4,
                border: "none",
                cursor: "pointer",
                background: effectiveSection === section ? c.panelAlt : "transparent",
                color: effectiveSection === section ? c.heading : c.textMuted,
              }}
            >
              {section}
              <span style={monoText(10, c.textFaint, { marginLeft: 6 })}>
                {grouped[activeTab][section].length}
              </span>
            </button>
          ))}
        </div>

        <div style={{ flex: 1, minWidth: 0, border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
          {rows.map((key, i) => (
            <div
              key={key}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 12,
                padding: "8px 16px",
                borderTop: i === 0 ? "none" : `1px solid ${c.border}`,
              }}
            >
              <div style={uiText(13, c.textMuted)} title={key}>
                {humanizeLabel(key)}
              </div>
              <ExpandableValue raw={settings[key]} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
