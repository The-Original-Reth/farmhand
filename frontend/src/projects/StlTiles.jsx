// The STL section's tile grid: each STL as a tile (preview, name, prints, buttons), its trash can, and the
// sub-component groups the tiles are set in
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Box, ChevronDown, Download, Folder, FolderInput, Layers } from "lucide-react";
import { deleteProjectFile } from "../api.js";
import { c, fs, ui, fixed } from "../theme.js";
import { useData } from "../data.jsx";
import { ConfirmDialog, DeleteWarning } from "../components/common/dialogs.jsx";
import { TrashButton } from "../components/common/ui.jsx";
import { toolButton, uiText } from "../styles.js";
import { nameStyle } from "./pieces.jsx";
import { plural } from "../lib/format.js";
import { shown } from "./stlComponents.js";

// The STLs side by side, as many to a row as fit, each tile a set width
const TILE_WIDTH = 212;
export function TileGrid({ children }) {
  return <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fill, ${TILE_WIDTH}px)`, gap: 10 }}>{children}</div>;
}

// A small button on a tile: just an icon (what it does on hover), or a link when `href` is given
function TileButton({ testId, Icon, title, onClick, href, children }) {
  const style = toolButton(12, { padding: "4px 7px", gap: 4, textDecoration: "none", whiteSpace: "nowrap" });
  return href ? (
    <a data-testid={testId} href={href} title={title} aria-label={title} style={style}>
      <Icon size={13} />
    </a>
  ) : (
    <button data-testid={testId} onClick={onClick} title={title} aria-label={title} style={style}>
      <Icon size={13} />
      {children}
    </button>
  );
}

// One STL as a tile: its newest version's preview (click it for every version), its name and tag, its newest version
// and date, how many prints it has and needs, and Download, Move, Versions and `last` (a trash can, or Take out)
export function StlTile({ testId, dataAttrs, name, thumb, tag, ver, versions, haveNeed, download, onMove, onDetails, last }) {
  return (
    // two rows of the same height: the preview takes as much room as the text under it
    <div data-testid={testId} {...dataAttrs} style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden", display: "grid", gridTemplateRows: "1fr 1fr", gridTemplateColumns: "minmax(0, 1fr)", minWidth: 0 }}>
      <button
        data-testid="stl-tile-preview"
        onClick={onDetails}
        title={`${name}: show every version`}
        style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", minHeight: 0, padding: 0, border: "none", borderBottom: `1px solid ${c.border}`, background: fixed.preview, cursor: "pointer" }}
      >
        {thumb ? (
          // filling the row, placed over it so the picture's own size never makes the row taller
          <img src={thumb} alt="" loading="lazy" decoding="async" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain" }} />
        ) : (
          <Box size={28} color={fixed.previewIcon} />
        )}
      </button>
      <div style={{ padding: "7px 8px 8px", display: "flex", flexDirection: "column", gap: 6, background: c.panelAlt, flex: 1 }}>
        <FitName name={name} />
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {tag}
          {ver && <span style={uiText(11, c.textFaint, { whiteSpace: "nowrap" })}>v{ver.v}{ver.date ? ` · ${ver.date}` : ""}</span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }} title="Prints: have / need">
          <span style={uiText(11, c.textFaint)}>Prints</span>
          {haveNeed}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: "auto" }}>
          {download && <TileButton testId="stl-tile-download" Icon={Download} title="Download its newest version" href={download} />}
          <TileButton testId="stl-tile-move" Icon={FolderInput} title="Move it to another sub-component" onClick={onMove} />
          <TileButton testId="stl-tile-versions" Icon={Layers} title="Every version, New version and the rest" onClick={onDetails}>
            {versions}
          </TileButton>
          <span style={{ marginLeft: "auto" }}>{last}</span>
        </div>
      </div>
    </div>
  );
}

// A tile's name, its text made smaller (down to 9) until it fits on the line; one still too long is cut short with "…"
// (the whole of it on hover)
function FitName({ name }) {
  const ref = useRef(null);
  const textRef = useRef(null); // the text itself: its whole width, even where it's cut short
  const [size, setSize] = useState(13);
  const [fontsIn, setFontsIn] = useState(0); // the web font changes how wide the name is: measured again once it's in
  useEffect(() => {
    let live = true;
    document.fonts?.ready.then(() => live && setFontsIn((n) => n + 1));
    return () => {
      live = false;
    };
  }, []);
  useLayoutEffect(() => setSize(13), [name, fontsIn]); // a new name starts again at full size
  useLayoutEffect(() => {
    const el = ref.current;
    const text = textRef.current;
    // a pixel to spare: widths are rounded, and one that only just fits is still cut short
    if (el && text && size > 9 && text.getBoundingClientRect().width > el.clientWidth - 1) setSize(size - 0.5);
  }, [size, name, fontsIn]);
  return (
    <div ref={ref} data-testid="stl-name" title={name} style={nameStyle({ minWidth: 0, fontSize: fs(size) })}>
      <span ref={textRef}>{name}</span>
    </div>
  );
}

// An uploaded STL's trash can: deletes it, every version (asked first)
export function DeleteStl({ project, file }) {
  const { putProject } = useData();
  const [asking, setAsking] = useState(false);
  return (
    <>
      <TrashButton onClick={() => setAsking(true)} title="Delete this STL file, every version" />
      {asking && (
        <ConfirmDialog
          title="Delete STL file"
          confirmLabel="Delete"
          onClose={() => setAsking(false)}
          onConfirm={async () => putProject(await deleteProjectFile("stl", project.id, file.id))}
        >
          Delete <strong>{file.name}</strong> and {file.versions.length === 1 ? "its only version" : `all ${file.versions.length} versions`}?
          <DeleteWarning>The files are deleted for good.</DeleteWarning>
        </ConfirmDialog>
      )}
    </>
  );
}

// One sub-component: its name and how many STLs are in it (click to fold them away), then its STLs, set in a little
export function ComponentGroup({ component, count, open, onToggle, children }) {
  const bodyId = `stl-component-${component}`;
  return (
    <div data-testid="stl-component" data-component={component} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <button
        data-testid="stl-component-toggle"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={onToggle}
        title={open ? "Fold it away" : "Show its STLs"}
        style={{ display: "flex", alignItems: "center", gap: 8, background: "none", border: "none", padding: "4px 0 0", cursor: "pointer", textAlign: "left", ...ui }}
      >
        <ChevronDown size={14} color={c.textFaint} style={{ transform: open ? "none" : "rotate(-90deg)", transition: "transform 0.12s ease", flexShrink: 0 }} />
        <Folder size={14} color={c.amber} style={{ flexShrink: 0 }} />
        <span style={uiText(14, c.heading, { wordBreak: "break-word" })}>{shown(component)}</span>
        <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap" })}>{plural(count, "STL")}</span>
      </button>
      {open && (
        <div id={bodyId} style={{ display: "flex", flexDirection: "column", gap: 10, paddingLeft: 14, borderLeft: `2px solid ${c.border}`, marginLeft: 6 }}>
          {children}
        </div>
      )}
    </div>
  );
}
