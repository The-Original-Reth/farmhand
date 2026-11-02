import { useMemo } from "react";
import { ChevronDown, Printer } from "lucide-react";
import { monoText, uiText } from "../styles.js";
import { boxStyle, SettingsPages, SlicerColors, slicerColors } from "../settings/fields.jsx";
import { hasValue, pagesWithContent } from "../settings/pages.js";
import { BOSS_CHOICES, bossPrinterPages, bossValue } from "../settings/boss.js";
import { useVersionSettings } from "../settings/useVersionSettings.js";

// A printer preset (a sub printer) laid out as PrusaSlicer's (and BOSS edition's) Printer Settings tab: the same
// pages down the left, the same titled groups on each page, the same labels and units, and one Extruder page per
// extruder (the layout is in settings/boss.js), in PrusaSlicer's colours. Read from a 3MF sliced with it, so it's
// read-only: the fields are drawn, never typed in.

// The Printer Settings pages for one 3MF version's settings (null: there's no 3MF to read them from), followed by
// `extraPages`: pages of Farmhand's own ({ id, title, Icon, render }), such as the sub printer's Printer parts
function PresetPages({ settings, extraPages = [] }) {
  const value = useMemo(() => bossValue(settings), [settings]);
  const pages = useMemo(() => pagesWithContent(bossPrinterPages(settings, extraPages), hasValue(value)), [settings, extraPages, value]);
  return <SettingsPages pages={pages} value={value} choices={BOSS_CHOICES} label="Printer Settings pages" />;
}

// Loads the version's settings, then shows them as the Printer Settings tab, with `extraPages` after them. `name` is the
// preset, shown at the top the way PrusaSlicer's preset drop-down shows it. `copied`: settings that come from elsewhere
// when there's no version, as { settings, error } (a copy's, copied from its original). With neither (no 3MF was sliced
// with it yet) only the extra pages are shown, under `empty`, which says why.
export function PrinterPresetPages({ ver, copied = null, name, from, extraPages, empty }) {
  const fromVersion = useVersionSettings(ver?.id);
  const { settings, error } = ver ? fromVersion : copied || { settings: null, error: null };
  const p = slicerColors("prusa");
  return (
    <SlicerColors.Provider value={p}>
    <div data-testid="slicer-window" style={{ background: p.bg, color: p.textPrimary, border: `1px solid ${p.border}`, borderRadius: 4, padding: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        <span style={boxStyle({ ...monoText(13, p.heading), padding: "5px 10px", gap: 8 }, p)}>
          <Printer size={14} color={p.accentText} />
          {name}
          <ChevronDown size={13} color={p.textFaint} />
        </span>
        {from}
      </div>
      {!ver && !copied ? (
        <>
          {empty}
          <PresetPages settings={null} extraPages={extraPages} />
        </>
      ) : error ? (
        <div style={uiText(13, p.accentText)}>Couldn't load its settings: {error}</div>
      ) : !settings ? (
        <div style={uiText(13, p.textFaint)}>Loading settings…</div>
      ) : (
        <PresetPages key={ver?.id ?? "copied"} settings={settings} extraPages={extraPages} />
      )}
    </div>
    </SlicerColors.Provider>
  );
}
