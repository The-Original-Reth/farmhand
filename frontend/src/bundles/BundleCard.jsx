import { Fragment } from "react";
import { c } from "../theme.js";
import { uiText } from "../styles.js";

import { NotesSection } from "../notes/NotesSection.jsx";
import { AddToProjectButton } from "../projects/AddToProject.jsx";
import { DeleteBundleButton, NewVersionButton } from "./bundleActions.jsx";
import { GcodeRow } from "./GcodeRow.jsx";
import { VersionRow } from "./VersionRow.jsx";
import { VersionsToggle } from "./versions.jsx";
import { plural } from "../lib/format.js";

// One 3MF file as a card: a heading (`title` on the left, which also shows/hides the older versions when clicked; the
// version count, that toggle, New version and Delete on the right), its newest version, the older ones when shown,
// each version's G-code (if it has one) on a line under it, and its notes. The Printers page titles it by file name;
// a model's page by printer.
// versions: newest first. grow: the title takes all the room it can.
export function BundleCard({ bundle: b, versions: vlist, title, grow = false, expansion, compareSelection, onToggleCompare }) {
  const latest = vlist[0];
  const rest = vlist.slice(1);
  const isExpanded = expansion.isExpanded(b.id, vlist.length);
  const isSelected = vlist.some((v) => compareSelection.includes(v.id)); // any of its versions picked
  return (
    <div
      data-testid="bundle-card"
      data-bundle-id={b.id}
      style={{
        border: `1px solid ${isSelected ? c.amber : c.border}`,
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 16px",
          background: c.panelAlt,
        }}
      >
        <div
          onClick={() => rest.length > 0 && expansion.set(b.id, !isExpanded)}
          style={{ display: "flex", flexDirection: "column", gap: 4, cursor: rest.length > 0 ? "pointer" : "default", minWidth: 0, ...(grow ? { flex: 1 } : {}) }}
        >
          {title}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <span style={uiText(12, c.textFaint)}>
            {plural(vlist.length, "version")}
          </span>
          {rest.length > 0 && (
            <VersionsToggle open={isExpanded} olderCount={rest.length} controlsId={`versions-${b.id}`} onToggle={() => expansion.set(b.id, !isExpanded)} />
          )}
          <AddToProjectButton bundle={b} />
          <NewVersionButton bundle={b} />
          <DeleteBundleButton bundle={b} />
        </div>
      </div>
      {latest && <VersionRow ver={latest} isLatest showFileStatus bundle={b} compareSelection={compareSelection} onToggleCompare={onToggleCompare} />}
      {latest?.gcodeName && <GcodeRow ver={latest} bundle={b} />}
      <div id={`versions-${b.id}`}>
        {isExpanded &&
          rest.map((v) => (
            <Fragment key={v.v}>
              <VersionRow ver={v} showFileStatus bundle={b} compareSelection={compareSelection} onToggleCompare={onToggleCompare} />
              {v.gcodeName && <GcodeRow ver={v} bundle={b} />}
            </Fragment>
          ))}
      </div>
      <div data-testid="bundle-notes" style={{ borderTop: `1px solid ${c.border}`, padding: "12px 16px 14px", background: c.panel }}>
        <NotesSection key={b.id} kind="bundle" owner={b} />
      </div>
    </div>
  );
}
