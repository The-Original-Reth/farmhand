import { useMemo, useRef, useState } from "react";
import { c } from "../theme.js";
import { uiText } from "../styles.js";
import { hasValue, pageKeys } from "../settings/pages.js";
import { layoutFor, SlicerWindow, slicerTabs } from "./SettingsBrowser.jsx";

// Two page bodies that scroll together while `linked`: scrolling one moves the other to the same place. The rows
// line up, so the same distance down shows the same settings. Gives each side the { ref, onScroll } to put on its
// body. `moved` remembers where we put the other side, so its own scroll event (fired by our move) isn't passed back.
function useLinkedScroll(linked) {
  const bodies = useRef({ left: null, right: null, moved: {} });
  const linkedRef = useRef(linked);
  linkedRef.current = linked;
  return useMemo(() => {
    const other = { left: "right", right: "left" };
    const one = (side) => ({
      ref: (el) => {
        bodies.current[side] = el;
      },
      onScroll: (e) => {
        const b = bodies.current;
        const top = e.currentTarget.scrollTop;
        if (b.moved[side] === top) {
          delete b.moved[side];
          return;
        }
        const target = b[other[side]];
        if (!linkedRef.current || !target || target.scrollTop === top) return;
        const before = target.scrollTop;
        target.scrollTop = top; // the browser stops it at the bottom if that side is shorter
        if (target.scrollTop !== before) b.moved[other[side]] = target.scrollTop;
      },
    });
    return { left: one("left"), right: one("right") };
  }, []);
}

// The two files side by side, each laid out as its slicer shows it, with the settings that differ marked. When both
// came from the same kind of slicer their pages line up, and choosing a tab or page on either side turns both, and
// scrolling one scrolls the other.
export function SlicerCompare({ left, right, leftLabel, rightLabel, leftSettings, rightSettings, differing, onlyDiffs }) {
  const leftLayout = layoutFor(left.version.slicerFamily);
  const rightLayout = layoutFor(right.version.slicerFamily);
  const linked = leftLayout.id === rightLayout.id;
  const [tabIds, setTabIds] = useState({ left: null, right: null });
  const [pageIds, setPageIds] = useState({ left: null, right: null });
  const scroll = useLinkedScroll(linked);

  const sides = useMemo(() => {
    const valueL = leftLayout.value(leftSettings);
    const valueR = rightLayout.value(rightSettings);
    const diffsOn = (page) => new Set(pageKeys(page).filter((k) => differing.has(k))).size;
    const shown = (own) => (onlyDiffs ? (key) => differing.has(key) : own);
    if (linked) {
      // one set of pages for both, with a row wherever either file has the setting, so the two sides line up
      const has = shown((key, page) => valueL(key, page) !== undefined || valueR(key, page) !== undefined);
      const tabs = slicerTabs(leftLayout, { ...rightSettings, ...leftSettings }, has);
      return { left: { tabs, value: valueL, has, diffsOn }, right: { tabs, value: valueR, has, diffsOn } };
    }
    const one = (layout, settings, value) => {
      const has = shown(hasValue(value));
      return { tabs: slicerTabs(layout, settings, has), value, has, diffsOn };
    };
    return { left: one(leftLayout, leftSettings, valueL), right: one(rightLayout, rightSettings, valueR) };
  }, [leftLayout, rightLayout, leftSettings, rightSettings, differing, onlyDiffs, linked]);

  const pane = (side, version, label, settings, layout) => {
    const s = sides[side];
    const key = linked ? "left" : side; // linked: both sides read and set the same choice
    return (
      <SlicerWindow
        layout={layout} tabs={s.tabs} settings={settings} value={s.value}
        title={`${label} · ${version.slicer || "unknown slicer"}`}
        tabId={tabIds[key]} pageId={pageIds[key]}
        onTab={(id) => {
          setTabIds((t) => ({ ...t, [key]: id }));
          setPageIds((p) => ({ ...p, [key]: null })); // a new tab opens on its first page
        }}
        onPage={(id) => setPageIds((p) => ({ ...p, [key]: id }))}
        compare={{ side, keys: differing, has: s.has, diffsOn: s.diffsOn, scroll: scroll[side] }}
      />
    );
  };

  return (
    <div data-testid="slicer-compare" style={{ padding: "14px 16px" }}>
      {!linked && (
        <div style={uiText(12, c.textMuted, { marginBottom: 10, lineHeight: 1.5 })}>
          These two were made in different slicers, so their pages don’t line up: each side turns on its own.
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(520px, 1fr))", gap: 12, alignItems: "start" }}>
        {pane("left", left.version, leftLabel, leftSettings, leftLayout)}
        {pane("right", right.version, rightLabel, rightSettings, rightLayout)}
      </div>
    </div>
  );
}
