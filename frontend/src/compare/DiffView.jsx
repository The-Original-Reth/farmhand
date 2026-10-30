import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { monoText, uiText } from "../styles.js";
import { categorizeKey, formatVal } from "../settingsLayout.js";
import { useData } from "../data.jsx";
import { useVersionSettings } from "../settings/useVersionSettings.js";
import { SlicerCompare } from "./SlicerCompare.jsx";

import { Badge } from "../components/common/ui.jsx";

const CATEGORY_ORDER = [
  "Layers & Perimeters", "Infill", "Support Material", "Skirt & Brim", "Speed", "Kinematics",
  "Retraction", "Temperature", "Cooling", "Filament", "Printer", "Custom G-code", "Other Settings",
];

// One setting's row. Memoized: stepping to the next difference redraws the two rows whose outline moves, not every
// row (there can be thousands). `look` changes with the colour scheme, font and size, which are changed in place.
const DiffRow = React.memo(function DiffRow({ settingKey: key, first, differs, isCurrent, leftSettings, rightSettings, rowRefs, look }) { // eslint-disable-line no-unused-vars
  return (
    <div
      ref={(el) => {
        rowRefs.current[key] = el;
      }}
      data-testid="diff-row"
      data-setting={key}
      data-differs={differs ? "true" : "false"}
      data-current={isCurrent ? "true" : "false"}
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(150px, 1fr) 210px 210px",
        alignItems: "start",
        gap: 8,
        padding: "8px 16px 8px 13px",
        borderTop: first ? "none" : `1px solid ${c.border}`,
        borderLeft: `3px solid ${differs ? c.amber : "transparent"}`,
        background: differs ? `${c.amber}14` : "transparent", // a faint wash across the whole row
        outline: isCurrent ? `2px solid ${c.amber}` : "none",
        outlineOffset: -2,
      }}
    >
      <div
        style={uiText(13, differs ? c.textPrimary : c.textFaint, { fontWeight: differs ? 500 : 400, paddingTop: 2, minWidth: 0, overflowWrap: "break-word" })}
        title={key}
      >
        {/* the variable name exactly as the 3MF has it, underscores and all; a long one wraps after an underscore */}
        {key.split("_").map((part, j) => (
          <React.Fragment key={j}>
            {j > 0 && <>_<wbr /></>}
            {part}
          </React.Fragment>
        ))}
      </div>
      <DiffValue settings={leftSettings} other={rightSettings} k={key} side="left" differs={differs} />
      <DiffValue settings={rightSettings} other={leftSettings} k={key} side="right" differs={differs} />
    </div>
  );
});

// ---------------------------------------------------------------------------
// Compare-across-printers diff view
// ---------------------------------------------------------------------------
// Which part of `mine` differs from `theirs`: what's left once the shared start and end are set aside.
// (0.18 vs 0.2 -> "18" / "2";  aligned vs aligned_rear -> "" / "_rear")
function changedParts(mine, theirs) {
  const max = Math.min(mine.length, theirs.length);
  let start = 0;
  while (start < max && mine[start] === theirs[start]) start++;
  let end = 0;
  while (end < max - start && mine[mine.length - 1 - end] === theirs[theirs.length - 1 - end]) end++;
  return { prefix: mine.slice(0, start), mid: mine.slice(start, mine.length - end), suffix: mine.slice(mine.length - end) };
}

// (a function, not a constant: the colours follow the scheme, which can change while a comparison is open)
const diffSide = () => ({
  left: { fg: c.amber, soft: c.amberDim, strong: c.amber, strongFg: c.onAccent },
  right: { fg: c.teal, soft: c.tealDim, strong: c.teal, strongFg: c.onTeal },
});

// One side of a settings row in the comparison. Unchanged values fade back; changed ones sit in a chip in
// that side's colour with the part that actually changed picked out; a setting the file doesn't have says so.
function DiffValue({ settings, other, k, side, differs }) {
  if (!(k in settings)) {
    return (
      <div data-testid="diff-absent" style={{ ...ui, fontSize: fs(12), fontStyle: "italic", color: differs ? c.textMuted : c.textFaint, paddingTop: 2 }}>
        not in this file
      </div>
    );
  }
  if (!differs) {
    return <div style={monoText(12, c.textFaint, { wordBreak: "break-word", paddingTop: 2 })}>{formatVal(settings[k])}</div>;
  }
  // a changed value is shown in full (a long one scrolls inside its chip), so what changed is never cut off
  const full = (v) => (v === undefined || v === null || v === "" ? "—" : String(v));
  const text = full(settings[k]);
  const s = diffSide()[side];
  const parts = k in other ? changedParts(text, full(other[k])) : null;
  return (
    <div
      data-testid="diff-value"
      data-side={side}
      title={String(settings[k] ?? "")}
      style={monoText(12, s.fg, { background: s.soft, padding: "2px 7px", borderRadius: 3, justifySelf: "start", maxWidth: "100%", maxHeight: 160, overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word" })}
    >
      {parts ? (
        <>
          {parts.prefix}
          {parts.mid && (
            <mark data-testid="diff-mark" style={{ background: s.strong, color: s.strongFg, borderRadius: 2, padding: "0 1px" }}>
              {parts.mid}
            </mark>
          )}
          {parts.suffix}
        </>
      ) : (
        text
      )}
    </div>
  );
}

export function DiffView({ left, right, onClose }) {
  // left / right are { bundle, version }: exactly the two versions that were picked
  const { versionLabel } = useData();
  const leftLabel = versionLabel(left);
  const rightLabel = versionLabel(right);
  const [onlyDiffs, setOnlyDiffs] = useState(false);
  const [view, setView] = useState("slicer"); // "slicer": side by side as the slicers show them | "list": every setting by name
  const { settings: leftSettings, error: leftError } = useVersionSettings(left.version.id);
  const { settings: rightSettings, error: rightError } = useVersionSettings(right.version.id);
  const loadError = leftError || rightError;
  const [cursor, setCursor] = useState(-1); // which difference the Previous/Next buttons are on
  const rowRefs = useRef({});

  useEffect(() => setCursor(-1), [left.version.id, right.version.id]);

  // Every setting by category, and which differ: worked out once per pair of versions, not on every click
  const derived = useMemo(() => {
    if (!leftSettings || !rightSettings) return null;
    const allKeys = Array.from(new Set([...Object.keys(leftSettings), ...Object.keys(rightSettings)]));
    const grouped = {};
    allKeys.forEach((key) => {
      const cat = categorizeKey(key);
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(key);
    });
    CATEGORY_ORDER.forEach((cat) => grouped[cat]?.sort());
    // A setting differs if its value differs, or if only one of the two files has it at all. This compares the
    // EXACT text: formatVal() shortens long values for display, and comparing the shortened text would call two
    // long values (a start G-code edited near its end, say) identical.
    const exactText = (settings, key) => (key in settings ? String(settings[key] ?? "") : null);
    const differing = new Set(allKeys.filter((key) => exactText(leftSettings, key) !== exactText(rightSettings, key)));
    const diffKeys = []; // in the order they appear on screen
    CATEGORY_ORDER.forEach((cat) => (grouped[cat] || []).forEach((key) => differing.has(key) && diffKeys.push(key)));
    return { allKeys, grouped, differing, diffKeys };
  }, [leftSettings, rightSettings]);

  if (loadError) {
    return <div style={uiText(13, c.amber, { padding: 16 })}>Couldn't load settings: {loadError}</div>;
  }
  if (!leftSettings || !rightSettings) {
    return <div style={uiText(13, c.textFaint, { padding: 16 })}>Loading settings…</div>;
  }

  const { allKeys, grouped, differing, diffKeys } = derived;
  const categoryOrder = CATEGORY_ORDER;
  const differsAt = (key) => differing.has(key);
  const look = `${c.bg}|${c.textPrimary}|${c.textFaint}|${c.amber}|${c.teal}|${ui.fontFamily}|${fs(10)}`; // the look, for DiffRow
  const diffCount = diffKeys.length;

  const goTo = (index) => {
    if (diffCount === 0) return;
    const i = ((index % diffCount) + diffCount) % diffCount; // wraps round at either end
    setCursor(i);
    rowRefs.current[diffKeys[i]]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const stepButton = {
    display: "flex", alignItems: "center", gap: 5, ...ui, fontSize: fs(12), background: "none", color: c.textMuted,
    border: `1px solid ${c.border}`, borderRadius: 3, padding: "4px 9px", cursor: diffCount ? "pointer" : "default",
    opacity: diffCount ? 1 : 0.45,
  };

  return (
    <div data-testid="diff-view" style={{ border: `1px solid ${c.borderStrong}`, borderRadius: 4 }}>
      {/* stays in view while the settings scroll underneath, so the buttons are always to hand */}
      <div
        style={{
          position: "sticky",
          top: -16, // the modal body has 16px of padding; this sticks flush to its top edge, with no strip of rows peeking above
          zIndex: 3,
          padding: "12px 16px",
          background: c.panelAlt,
          borderBottom: `1px solid ${c.border}`,
          borderTopLeftRadius: 3,
          borderTopRightRadius: 3,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={uiText(13, c.textMuted, { lineHeight: 1.5 })}>
          Comparing <span style={{ color: c.amber, fontWeight: 600 }}>{leftLabel}</span>{" "}
          (left) against <span style={{ color: c.teal, fontWeight: 600 }}>{rightLabel}</span> (right)
          <div data-testid="diff-summary" style={{ color: c.textFaint }}>
            {allKeys.length} settings,{" "}
            <span style={{ color: diffCount ? c.amber : c.textFaint, fontWeight: diffCount ? 600 : 400 }}>{diffCount} differ</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <div role="radiogroup" aria-label="How to show them" style={{ display: "flex", border: `1px solid ${c.border}`, borderRadius: 3, overflow: "hidden" }}>
            {[["slicer", "Slicer view"], ["list", "List"]].map(([id, name]) => (
              <button
                key={id}
                role="radio"
                aria-checked={view === id}
                data-testid={`diff-view-${id}`}
                onClick={() => setView(id)}
                style={{
                  ...ui, fontSize: fs(12), padding: "4px 10px", border: "none", cursor: "pointer",
                  background: view === id ? c.amberDim : "transparent", color: view === id ? c.amber : c.textMuted, fontWeight: view === id ? 600 : 400,
                }}
              >
                {name}
              </button>
            ))}
          </div>
          {view === "list" && (
            <>
          <button data-testid="diff-prev" onClick={() => goTo(cursor < 0 ? diffCount - 1 : cursor - 1)} disabled={!diffCount} style={stepButton}>
            <ArrowUp size={12} />
            Previous
          </button>
          <button data-testid="diff-next" onClick={() => goTo(cursor + 1)} disabled={!diffCount} style={stepButton}>
            <ArrowDown size={12} />
            Next difference
          </button>
          <span data-testid="diff-position" style={monoText(11, c.textFaint, { minWidth: 54 })}>
            {diffCount ? (cursor >= 0 ? `${cursor + 1} of ${diffCount}` : `${diffCount} total`) : ""}
          </span>
            </>
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(12), color: c.textMuted, cursor: "pointer", flexShrink: 0 }}>
            <input type="checkbox" checked={onlyDiffs} onChange={(e) => setOnlyDiffs(e.target.checked)} style={{ accentColor: c.amber }} />
            Only show differences
          </label>
        </div>
      </div>

      {diffCount === 0 && (
        <div data-testid="diff-identical" style={uiText(13, c.textMuted, { padding: "14px 16px", borderBottom: `1px solid ${c.border}` })}>
          These two versions have identical settings.
        </div>
      )}

      {view === "slicer" ? (
        <SlicerCompare
          left={left} right={right} leftLabel={leftLabel} rightLabel={rightLabel}
          leftSettings={leftSettings} rightSettings={rightSettings} differing={differing} onlyDiffs={onlyDiffs}
        />
      ) : (
      <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 20 }}>
        {categoryOrder.map((cat) => {
          const keys = grouped[cat];
          if (!keys || keys.length === 0) return null;
          const catDiffs = keys.filter(differsAt).length;
          const visibleKeys = onlyDiffs ? keys.filter(differsAt) : keys;
          if (visibleKeys.length === 0) return null;
          return (
            <div key={cat}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={uiText(12, c.textFaint, { textTransform: "uppercase", letterSpacing: 0.4 })}>{cat}</span>
                {catDiffs > 0 ? (
                  <span data-testid="diff-category-count"><Badge tone="amber">{catDiffs} of {keys.length} differ</Badge></span>
                ) : (
                  <span style={uiText(11, c.textFaint)}>no differences</span>
                )}
              </div>
              <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(150px, 1fr) 210px 210px",
                    padding: "6px 16px 6px 19px",
                    fontSize: fs(11),
                    background: c.panelAlt,
                    borderBottom: `1px solid ${c.border}`,
                    gap: 8,
                  }}
                >
                  <div style={{ color: c.textFaint }}>Setting</div>
                  <div style={{ lineHeight: 1.3, color: c.amber }}>{leftLabel}</div>
                  <div style={{ lineHeight: 1.3, color: c.teal }}>{rightLabel}</div>
                </div>
                {visibleKeys.map((key, i) => (
                  <DiffRow
                    key={key}
                    settingKey={key}
                    first={i === 0}
                    differs={differsAt(key)}
                    isCurrent={diffKeys[cursor] === key}
                    leftSettings={leftSettings}
                    rightSettings={rightSettings}
                    rowRefs={rowRefs}
                    look={look}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      )}
    </div>
  );
}
