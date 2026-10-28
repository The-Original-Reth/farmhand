import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { toolButton } from "../styles.js";
import { useData } from "../data.jsx";

import { readStoredObject, writeStored } from "../lib/storage.js";

// Which 3MF entries show all their versions. By default an entry shows just its newest version, with a toggle for
// the older ones. Only entries someone has explicitly opened or closed are remembered (in this browser). Shared by
// the model page and the printer page, so opening an entry on one opens it on the other too.
// (The key changed when "hidden" became the default for every entry, so choices made under the old default reset.)
const EXPANSION_KEY = "farmhand.bundleExpanded.v2";
export function useBundleExpansion() {
  const { bundles } = useData();
  const [explicit, setExplicit] = useState(() => readStoredObject(EXPANSION_KEY));
  const isExpanded = (id) => explicit[id] === true; // older versions start hidden
  const apply = (changes) =>
    setExplicit((prev) => {
      const live = new Set(bundles.map((b) => String(b.id)));
      const next = {};
      Object.entries({ ...prev, ...changes }).forEach(([id, open]) => {
        if (live.has(String(id)) && typeof open === "boolean") next[id] = open; // forget entries that no longer exist
      });
      writeStored(EXPANSION_KEY, next);
      return next;
    });
  return {
    isExpanded,
    set: (id, open) => apply({ [id]: open }),
    setMany: (ids, open) => apply(Object.fromEntries(ids.map((id) => [id, open]))),
  };
}

// Shows or hides an entry's older versions — a button in its header, beside "New version"
export function VersionsToggle({ open, olderCount, onToggle, controlsId }) {
  const [hover, setHover] = useState(false);
  const word = `older version${olderCount === 1 ? "" : "s"}`;
  return (
    <button
      data-testid="versions-toggle"
      aria-expanded={open}
      aria-controls={controlsId}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex", alignItems: "center", gap: 5, ...ui, fontSize: fs(12), cursor: "pointer", flexShrink: 0,
        background: hover ? c.panel : "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3,
        padding: "0 9px", height: 26,
      }}
    >
      <ChevronRight size={12} style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform 0.12s ease" }} />
      {open ? `Hide ${olderCount} ${word}` : `Show ${olderCount} ${word}`}
    </button>
  );
}

// Collapse / expand every entry on the page that has older versions
export function VersionsToggleAll({ bundleList, expansion }) {
  const withOlder = bundleList.filter((b) => b.versions.length > 1);
  if (withOlder.length === 0) return null;
  const anyOpen = withOlder.some((b) => expansion.isExpanded(b.id, b.versions.length));
  return (
    <button
      data-testid="versions-toggle-all"
      onClick={() => expansion.setMany(withOlder.map((b) => b.id), !anyOpen)}
      style={toolButton(12, { marginBottom: 10 })}
    >
      <ChevronRight size={12} style={{ transform: anyOpen ? "rotate(90deg)" : "none" }} />
      {anyOpen ? "Collapse all versions" : "Expand all versions"}
    </button>
  );
}

// Entries (3MFs) under a printer: the one updated most recently first
export const newestFirst = (a, b) => (Date.parse(b.updated) || 0) - (Date.parse(a.updated) || 0) || b.id - a.id;
