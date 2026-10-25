import React, { useState, useEffect, useLayoutEffect, useRef } from "react";
import {
  Printer,
  ChevronRight,
  Star,
  Lock,
  Wifi,
  Cable,
  Archive,
  FileBox,
  Layers,
  Download,
  X,
  Upload,
  GitCompare,
  CheckSquare,
  Square,
  SlidersHorizontal,
  Trash2,
  Pencil,
  HardDrive,
  Palette,
  StickyNote,
  Folder,
  ArrowUp,
  FolderPlus,
  Server,
  Search,
  ArrowDown,
  Wrench,
  RefreshCw,
  ExternalLink,
  Check,
} from "lucide-react";

import { c, ui, mono, fs } from "./theme.js";
import { loadAppearance, saveAppearance, applyAppearance, normalizeAppearance } from "./appearance.js";
import { AppearanceSection } from "./AppearanceSection.jsx";
import {
  categorizeKey,
  humanizeLabel,
  formatVal,
  PRUSA_SECTIONS,
  classifyPrusa,
} from "./settingsLayout.js";
import {
  API_BASE,
  fetchVersionSettings,
  createSourceModel,
  createBundle,
  createPrinter,
  inspectThreemf,
  normalizePrinter,
  updatePrinter,
  addSourceModelVersion,
  deleteBundleVersion,
  deleteBundle,
  deleteSourceModelVersion,
  deleteSourceModel,
  getStorageSettings,
  saveStorageSettings,
  browseStorage,
  migrateStorage,
  createFolder,
  getShares,
  createShare,
  updateShare,
  reconnectShare,
  deleteShare,
  scanStlFolder,
  importScannedFiles,
  redrawPreview,
  bustThumbnails,
  addBundleVersion,
  getConfig,
  saveConfig,
  inspectConfigFolder,
  setConfigLocation,
  saveConfigNow,
  saveModelNotes,
  savePrinterNotes,
  renameModel,
  renameBundleVersion,
  saveBundleNotes,
  setStarredVersion,
  getMoonrakerStatus,
  syncPrinterHistory,
  getPrintStats,
  getEnergy,
  getPrintJobs,
  getMaintenance,
  addMaintenance,
  updateMaintenance,
  performMaintenance,
  deleteMaintenance,
  serviceDone,
  setServiceEnabled,
  saveServiceNotes,
  saveConfigOnExit,
  restoreConfig,
  bundle3mfUrl,
  sourceModelDownloadUrl,
} from "./api.js";
import { DataProvider, useData } from "./data.jsx";
import { parseLocation, describeLocation } from "./location.js";

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
      style={{
        ...mono,
        fontSize: fs(12),
        color: c.textPrimary,
        wordBreak: "break-word",
        whiteSpace: expanded ? "pre-wrap" : "normal",
        cursor: overflows ? "pointer" : "default",
      }}
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

function Crumb({ items, onJump }) {
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

function Badge({ children, tone = "muted" }) {
  const tones = {
    muted: { bg: c.panelAlt, fg: c.textMuted, border: c.border },
    amber: { bg: c.amberDim, fg: c.amber, border: c.amberBorder },
    teal: { bg: c.tealDim, fg: c.teal, border: c.tealBorder },
    green: { bg: c.greenDim, fg: c.green, border: c.greenBorder },
    danger: { bg: c.dangerDim, fg: c.danger, border: c.danger },
  };
  const t = tones[tone];
  return (
    <span
      style={{
        ...ui,
        fontSize: fs(12),
        padding: "2px 8px",
        borderRadius: 3,
        background: t.bg,
        color: t.fg,
        border: `1px solid ${t.border}`,
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function Row({ children, onClick, hoverable = true }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        alignItems: "center",
        padding: "12px 16px",
        borderBottom: `1px solid ${c.border}`,
        background: hoverable && hover ? c.panelHover : "transparent",
        cursor: onClick ? "pointer" : "default",
        transition: "background 0.1s ease",
      }}
    >
      {children}
    </div>
  );
}

function SectionLabel({ children }) {
  return (
    <div style={{ ...ui, fontSize: fs(13), color: c.textFaint, marginBottom: 10 }}>
      {children}
    </div>
  );
}

function CompareSelectButton({ selected, onClick }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      title={selected ? "Remove from compare" : "Select for compare"}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 5,
        ...ui,
        fontSize: fs(12),
        border: `1px solid ${selected ? c.amber : c.border}`,
        background: selected ? c.amberDim : "transparent",
        color: selected ? c.amber : c.textMuted,
        borderRadius: 3,
        padding: "4px 9px",
        cursor: "pointer",
      }}
    >
      {selected ? <CheckSquare size={13} /> : <Square size={13} />}
      {selected ? "Selected" : "Compare"}
    </button>
  );
}

function DownloadButton({ disabled, href }) {
  const style = {
    display: "flex",
    alignItems: "center",
    gap: 5,
    border: `1px solid ${disabled ? c.border : c.borderStrong}`,
    background: disabled ? "transparent" : c.panelAlt,
    color: disabled ? c.textFaint : c.textMuted,
    borderRadius: 3,
    padding: "4px 9px",
    fontSize: fs(12),
    cursor: disabled ? "not-allowed" : "pointer",
    textDecoration: "none",
    ...ui,
  };
  const title = disabled ? "Original file pruned — parameters only" : "Download";
  if (disabled || !href) {
    return (
      <button onClick={(e) => e.stopPropagation()} disabled={disabled} title={title} style={style}>
        <Download size={12} />
        Download
      </button>
    );
  }
  return (
    <a href={href} onClick={(e) => e.stopPropagation()} title={title} style={style} download>
      <Download size={12} />
      Download
    </a>
  );
}

// Square preview tile. Renders a real embedded/rendered image when given one;
// falls back to a quiet placeholder otherwise.
function Thumb({ src, size = 36, plateGrid = false, background, placeholderIcon = false }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: 3,
        border: `1px solid ${c.border}`,
        background: background || c.panelAlt,
        overflow: "hidden",
        flexShrink: 0,
        position: "relative",
      }}
    >
      {src ? (
        <img src={src} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
      ) : placeholderIcon ? (
        <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <FileBox size={Math.round(size * 0.4)} color="#C7CACC" />
        </div>
      ) : (
        <div style={{ width: "100%", height: "100%" }} />
      )}
      {plateGrid && (
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 3,
            background: c.borderStrong,
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Deleting
// ---------------------------------------------------------------------------
function TrashButton({ onClick, title }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title={title}
      aria-label={title}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: 26,
        height: 26,
        flexShrink: 0,
        borderRadius: 3,
        border: `1px solid ${hover ? c.danger : c.border}`,
        background: hover ? c.dangerDim : "transparent",
        color: hover ? c.danger : c.textFaint,
        cursor: "pointer",
      }}
    >
      <Trash2 size={13} />
    </button>
  );
}

// Every destructive action goes through this: say exactly what will happen,
// then do it only on an explicit second click.
function ConfirmDialog({ title, confirmLabel = "Delete", tone = "danger", onConfirm, onClose, children }) {
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const run = async () => {
    setSubmitting(true);
    setErrorMsg(null);
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
      setSubmitting(false);
    }
  };

  return (
    <Modal title={title} onClose={submitting ? () => {} : onClose} width={480}>
      <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6, marginBottom: 14 }}>{children}</div>
      {errorMsg && (
        <div style={{ ...ui, fontSize: fs(12), color: tone === "danger" ? c.danger : c.amber, marginBottom: 10, lineHeight: 1.5 }}>{errorMsg}</div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button
          onClick={onClose}
          disabled={submitting}
          style={{ ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "7px 14px", cursor: submitting ? "default" : "pointer" }}
        >
          Cancel
        </button>
        <button
          onClick={run}
          disabled={submitting}
          style={{ ...ui, fontSize: fs(13), background: tone === "danger" ? c.danger : c.amber, color: tone === "danger" ? c.onDanger : c.onAccent, border: "none", borderRadius: 3, padding: "7px 14px", fontWeight: 600, cursor: submitting ? "default" : "pointer", opacity: submitting ? 0.7 : 1 }}
        >
          {submitting ? (tone === "danger" ? "Deleting…" : "Working…") : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

function DeleteWarning({ children }) {
  return <div style={{ color: c.amber, marginTop: 8 }}>{children}</div>;
}

// Add a newer version to an existing 3MF entry. It becomes the top version; the older ones stay below it.
function NewBundleVersionDialog({ bundle, onClose }) {
  const { refresh } = useData();
  const [threemf, setThreemf] = useState(null);
  const [gcode, setGcode] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const current = bundle.versions[0]?.v || 0;

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!threemf) return setErrorMsg("Drop the newer .3mf file first.");
    setSubmitting(true);
    try {
      await addBundleVersion({ bundleId: bundle.id, threemf, gcode });
      await refresh();
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6, marginBottom: 14 }}>
        Adds a new version to <span style={mono}>{bundle.name}</span>, which is at v{current} now. The new file becomes{" "}
        <b style={{ color: c.heading }}>v{current + 1}</b> and is shown above the older versions. It has to be sliced for the
        same printer as this entry.
      </div>
      <Dropzone label="Drop the newer .3mf file here" file={threemf} onFile={setThreemf} accept=".3mf" />
      <Dropzone label="Drop the matching .gcode file here (optional)" file={gcode} onFile={setGcode} accept=".gcode,.gco" />
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel="Add new version" submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}

function NewVersionButton({ bundle }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        data-testid="new-version"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        title="Upload a newer version of this 3MF"
        style={{ display: "flex", alignItems: "center", gap: 5, ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "0 9px", height: 26, cursor: "pointer", flexShrink: 0 }}
      >
        <Upload size={12} />
        New version
      </button>
      {open && (
        <Modal title="Upload a new version" onClose={() => setOpen(false)}>
          <NewBundleVersionDialog bundle={bundle} onClose={() => setOpen(false)} />
        </Modal>
      )}
    </>
  );
}

// Delete a whole 3MF entry (every version) — the trash icon in a bundle's header
function DeleteBundleButton({ bundle }) {
  const { refresh } = useData();
  const [open, setOpen] = useState(false);
  const monuments = bundle.versions.filter((v) => v.monument);
  return (
    <>
      <TrashButton title="Delete this 3MF and all its versions" onClick={() => setOpen(true)} />
      {open && (
        <ConfirmDialog
          title="Delete 3MF"
          onClose={() => setOpen(false)}
          onConfirm={async () => {
            await deleteBundle(bundle.id);
            await refresh();
          }}
        >
          <div>
            Permanently delete <span style={mono}>{bundle.name}</span> and{" "}
            {bundle.versions.length === 1 ? "its only version" : `all ${bundle.versions.length} of its versions`}? The
            3MF and gcode files, thumbnails and parsed settings are removed. This can't be undone.
          </div>
          {monuments.length > 0 && (
            <DeleteWarning>
              {monuments.length === 1 ? "One version is" : `${monuments.length} versions are`} flagged as a monument —
              those are meant to be kept, and will be deleted too.
            </DeleteWarning>
          )}
        </ConfirmDialog>
      )}
    </>
  );
}

// Stars are real metal colours, not theme roles: the initial version is silver and the starred version is gold in
// every scheme (the theme's "amber" is blue or violet in some of them). Each has a darker edge so it holds up on
// light backgrounds.
const STAR_GOLD = "#F2C230";
const STAR_GOLD_EDGE = "#B8860B";
const STAR_SILVER = "#C9CDD3";
const STAR_SILVER_EDGE = "#868B93";

// The star beside a 3MF version's thumbnail. v1, the initial upload, is always silver. Every later version has an
// outline star; clicking one turns it gold, and only one version of a 3MF is gold at a time, so starring another
// moves it. Clicking the gold one clears it. The star changes at once; if the save fails it goes back and says why.
function VersionStar({ bundle, ver }) {
  const { refresh } = useData();
  const [pending, setPending] = useState(undefined); // the starred version id being saved (null = clearing)
  const [error, setError] = useState(null);
  const [hover, setHover] = useState(false);

  if (ver.v === 1) {
    return <Star data-testid="initial-star" size={13} color={STAR_SILVER_EDGE} fill={STAR_SILVER} aria-label="Initial version" />;
  }

  const busy = pending !== undefined;
  const starred = (busy ? pending : bundle.starredVersionId) === ver.id;
  const label = error ? `Couldn't save the star: ${error}` : starred ? "Starred — click to un-star" : `Star v${ver.v}`;
  const toggle = async (e) => {
    e.stopPropagation();
    if (busy) return;
    const next = starred ? null : ver.id;
    setError(null);
    setPending(next);
    try {
      await setStarredVersion({ bundleId: bundle.id, versionId: next });
      await refresh();
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setPending(undefined);
    }
  };
  return (
    <button
      data-testid="version-star"
      data-starred={starred ? "true" : "false"}
      aria-pressed={starred}
      onClick={toggle}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title={label}
      aria-label={label}
      style={{
        display: "flex", alignItems: "center", justifyContent: "center", width: 20, height: 20, padding: 0,
        border: "none", background: "none", cursor: busy ? "default" : "pointer",
        color: error ? c.danger : starred ? STAR_GOLD_EDGE : hover ? c.textMuted : c.textFaint,
      }}
    >
      <Star size={13} fill={starred ? STAR_GOLD : "none"} />
    </button>
  );
}

// Notes about one 3MF entry (shared by all its versions), at the foot of its card. Starts folded, like every notes box.
function BundleNotes({ bundle }) {
  return (
    <div data-testid="bundle-notes" style={{ borderTop: `1px solid ${c.border}`, padding: "12px 16px 14px", background: c.panel }}>
      <NotesSection
        kind="bundle"
        ownerId={bundle.id}
        saved={bundle.notes}
        rev={bundle.notesRevision}
        updatedAt={bundle.notesUpdatedAt}
        onSave={({ notes, baseRevision }) => saveBundleNotes({ bundleId: bundle.id, notes, baseRevision })}
        description="About this 3MF — what the settings are tuned for, plate setup, how it printed."
        placeholder="Nothing written yet. Notes you add here are kept with this 3MF and every version of it."
      />
    </div>
  );
}

// A file's name with a pencil beside it: click the pencil to rename it in place (Enter saves, Escape cancels).
// Only the part before the extension can be edited: the extension (.stl, .3mf...) is shown beside the box and always
// kept. The name is what Farmhand shows, searches by and downloads as; the stored file keeps its own name.
// `children` is how the name normally looks (e.g. with search words highlighted); `textStyle` styles the edit box.
const splitExtension = (name, fallback) => {
  const m = /^(.*?)(\.[^./\\]+)$/.exec(name);
  return m && m[1] ? [m[1], m[2]] : [name, fallback];
};
// `boxed` draws a box around the name, in the 3MF file name colour (c.fileName, set on the Appearance page).
function EditableName({ value, onSave, label, textStyle, testId, extension: fallbackExtension, boxed = false, children }) {
  const { refresh } = useData();
  const [stem, extension] = splitExtension(value, fallbackExtension);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(stem);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [hover, setHover] = useState(false);
  const inputRef = useRef(null);
  const stop = (e) => e.stopPropagation(); // the name often sits in a header that folds or opens when clicked
  // After a refused save, put the cursor back in the box (it's disabled while saving, which loses the focus)
  useEffect(() => {
    if (error && !busy) inputRef.current?.focus();
  }, [error, busy]);

  const start = (e) => {
    stop(e);
    setText(stem);
    setError(null);
    setEditing(true);
  };
  const cancel = () => {
    setEditing(false);
    setError(null);
  };
  const save = async () => {
    if (text.trim() === stem) return cancel();
    setBusy(true);
    setError(null);
    try {
      await onSave(text.trim() + extension); // the extension always stays as it was
      await refresh();
      setEditing(false);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!editing) {
    return (
      <span data-testid={testId} style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
        {boxed ? (
          <span
            data-testid={testId && `${testId}-box`}
            style={{ display: "inline-block", minWidth: 0, overflowWrap: "anywhere", border: `1px solid ${c.borderStrong}`, borderRadius: 3, background: c.panel, padding: "2px 7px", color: c.fileName }}
          >
            {children ?? value}
          </span>
        ) : (
          children ?? value
        )}
        <button
          data-testid={testId && `${testId}-edit`}
          onClick={start}
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => setHover(false)}
          title={`Rename ${label}`}
          aria-label={`Rename ${label}`}
          style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 20, height: 20, padding: 0, flexShrink: 0, background: "none", border: "none", cursor: "pointer", color: hover ? c.amber : c.textFaint }}
        >
          <Pencil size={12} />
        </button>
      </span>
    );
  }
  const iconButton = { display: "inline-flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, padding: 0, flexShrink: 0, borderRadius: 3, cursor: busy ? "default" : "pointer" };
  return (
    <span onClick={stop} style={{ display: "inline-flex", flexDirection: "column", gap: 3, minWidth: 0, flex: "1 1 auto", width: "100%", maxWidth: 560 }}>
      <span style={{ display: "flex", alignItems: "center", gap: 4, width: "100%" }}>
        <input
          ref={inputRef}
          data-testid={testId && `${testId}-input`}
          autoFocus
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onFocus={(e) => e.target.select()}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") cancel();
          }}
          aria-label={`New name for ${label}, without ${extension}`}
          spellCheck={false}
          style={{ ...textStyle, flex: 1, minWidth: 220, background: c.panel, border: `1px solid ${error ? c.danger : c.amber}`, borderRadius: 3, padding: "3px 6px", color: c.heading, outline: "none" }}
        />
        <span data-testid={testId && `${testId}-extension`} title="The extension always stays" style={{ ...textStyle, color: c.textMuted, flexShrink: 0 }}>
          {extension}
        </span>
        <button data-testid={testId && `${testId}-save`} onClick={save} disabled={busy} title="Save (Enter)" aria-label="Save name" style={{ ...iconButton, border: `1px solid ${c.amber}`, background: c.amber, color: c.onAccent }}>
          <Check size={13} />
        </button>
        <button onClick={cancel} disabled={busy} title="Cancel (Escape)" aria-label="Cancel renaming" style={{ ...iconButton, border: `1px solid ${c.border}`, background: "none", color: c.textMuted }}>
          <X size={13} />
        </button>
      </span>
      {error && <span style={{ ...ui, fontSize: fs(11), color: c.danger }}>{error}</span>}
    </span>
  );
}

// Delete a whole STL folder
function DeleteModelButton({ model, onDeleted }) {
  const { bundlesForModel, refresh } = useData();
  const [open, setOpen] = useState(false);
  const related = bundlesForModel(model.id);
  const exclusive = related.filter((b) => b.sourceModelIds.length === 1); // sliced only from this model
  const shared = related.filter((b) => b.sourceModelIds.length > 1); // mixed plates that also use other models
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        style={{ display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 4, padding: "5px 10px", cursor: "pointer", marginBottom: 10 }}
      >
        <Trash2 size={12} />
        Delete folder
      </button>
      {open && (
        <ConfirmDialog
          title="Delete STL folder"
          confirmLabel={exclusive.length > 0 ? "Delete folder and 3MF files" : "Delete folder"}
          onClose={() => setOpen(false)}
          onConfirm={async () => {
            await deleteSourceModel(model.id, { cascade: exclusive.length > 0 });
            onDeleted?.();
            await refresh();
          }}
        >
          <div>
            Permanently delete <span style={mono}>{model.name}</span>
            {model.versions.length > 0
              ? ` and ${model.versions.length === 1 ? "its file" : `all ${model.versions.length} versions of its file`}`
              : ""}
            ? This can't be undone.
          </div>
          {exclusive.length > 0 && (
            <DeleteWarning>
              This will also permanently delete {exclusive.length === 1 ? "this 3MF" : `these ${exclusive.length} 3MFs`},
              which {exclusive.length === 1 ? "was" : "were"} sliced only from this model:
              <div style={{ ...mono, fontSize: fs(11), marginTop: 6, color: c.textMuted, lineHeight: 1.7 }}>
                {exclusive.map((b) => (
                  <div key={b.id}>{b.name}</div>
                ))}
              </div>
            </DeleteWarning>
          )}
          {shared.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {shared.length === 1 ? "1 other 3MF is a mixed plate" : `${shared.length} other 3MFs are mixed plates`} that
              also use other models. {shared.length === 1 ? "It's" : "They're"} kept, just no longer linked to this one.
            </div>
          )}
        </ConfirmDialog>
      )}
    </>
  );
}

// Add a file to an STL folder that has none (e.g. created empty, or its only version was deleted)
function AddModelFileForm({ model, isNewVersion = false, onClose }) {
  const { refresh } = useData();
  const [file, setFile] = useState(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!file) return setErrorMsg("Choose an STL / OBJ / STEP file first.");
    setSubmitting(true);
    try {
      await addSourceModelVersion({ modelId: model.id, file, note: note.trim() });
      await refresh();
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      {isNewVersion && (
        <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6, marginBottom: 14 }}>
          Adds a new version of <span style={mono}>{model.name}</span>. It becomes{" "}
          <b style={{ color: c.heading }}>v{(model.versions[0]?.v || 0) + 1}</b> and is shown above the older versions.
        </div>
      )}
      <Dropzone
        label={isNewVersion ? "Drop the newer STL / OBJ / STEP file here" : "Drop an STL / OBJ / STEP file here"}
        file={file}
        onFile={setFile}
        accept=".stl,.obj,.step,.stp"
      />
      <TextField label="What changed? (optional)" value={note} onChange={setNote} placeholder="e.g. thicker legs" />
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel={isNewVersion ? "Upload version" : "Add file"} submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}

function VersionRow({ ver, isLatest, showFileStatus, bundle, model, compareSelection = [], onToggleCompare }) {
  const { refresh } = useData();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const isBundleRow = showFileStatus && !!bundle; // a 3MF version
  const isModelRow = !showFileStatus && !!model; // an STL/OBJ/STEP version
  const onlyVersion = isBundleRow ? bundle.versions.length <= 1 : isModelRow ? model.versions.length <= 1 : false;

  return (
    <div
      data-testid="version-row"
      data-version={ver.v}
      style={{
        display: "grid",
        gridTemplateColumns: showFileStatus
          ? "36px 24px 60px 90px 1fr 110px 104px 240px"
          : "24px 60px 90px 1fr 150px",
        alignItems: "center",
        padding: "9px 16px",
        borderTop: isLatest ? "none" : `1px solid ${c.border}`,
        gap: 8,
      }}
    >
      {showFileStatus && <Thumb src={ver.thumb} size={36} plateGrid />}
      <div>{isBundleRow && <VersionStar bundle={bundle} ver={ver} />}</div>
      <div style={{ ...mono, fontSize: fs(13), color: isLatest ? c.heading : c.textPrimary }}>
        v{ver.v}
      </div>
      <div style={{ ...mono, fontSize: fs(12), color: c.textMuted }}>{ver.date}</div>
      <div style={{ ...ui, fontSize: fs(13), color: ver.note ? c.textMuted : c.textFaint }}>
        {ver.note || "—"}
      </div>
      {showFileStatus && (
        <div>{ver.full ? <Badge tone="teal">full files</Badge> : <Badge>params only</Badge>}</div>
      )}
      {showFileStatus && (
        <div data-testid="compare-cell">
          {isBundleRow && onToggleCompare && (
            <CompareSelectButton selected={compareSelection.includes(ver.id)} onClick={() => onToggleCompare(ver.id)} />
          )}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 6 }}>
        {isBundleRow && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setSettingsOpen(true);
            }}
            title="Display settings"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              border: `1px solid ${c.borderStrong}`,
              background: c.panelAlt,
              color: c.textMuted,
              borderRadius: 3,
              padding: "4px 9px",
              fontSize: fs(12),
              cursor: "pointer",
              ...ui,
            }}
          >
            <SlidersHorizontal size={12} />
            Settings
          </button>
        )}
        <DownloadButton
          disabled={showFileStatus && !ver.full}
          href={showFileStatus ? bundle3mfUrl(ver.id) : model ? sourceModelDownloadUrl(model.id, ver.v) : undefined}
        />
        {(isBundleRow || isModelRow) && (
          <TrashButton title="Delete this version" onClick={() => setDeleteOpen(true)} />
        )}
      </div>

      {settingsOpen && bundle && (
        <Modal title="Display Settings" onClose={() => setSettingsOpen(false)} width={860}>
          <SettingsViewer bundle={bundle} ver={ver} />
        </Modal>
      )}

      {deleteOpen && (
        <ConfirmDialog
          title={isBundleRow ? "Delete 3MF version" : "Delete model file version"}
          onClose={() => setDeleteOpen(false)}
          onConfirm={async () => {
            if (isBundleRow) await deleteBundleVersion(ver.id);
            else await deleteSourceModelVersion(model.id, ver.v);
            await refresh();
          }}
        >
          <div>
            Permanently delete <b style={{ color: c.heading }}>v{ver.v}</b> of{" "}
            <span style={mono}>{isBundleRow ? ver.filename || bundle.name : model.name}</span>?{" "}
            {isBundleRow
              ? "Its 3MF and gcode files, thumbnail and parsed settings are removed."
              : "Its file is removed."}{" "}
            This can't be undone.
          </div>
          {ver.monument && (
            <DeleteWarning>
              This version is flagged as a monument{ver.note ? ` (“${ver.note}”)` : ""}. Monuments are meant to be kept —
              this deletes it anyway.
            </DeleteWarning>
          )}
          {onlyVersion && isBundleRow && (
            <DeleteWarning>It's the only version, so the whole 3MF entry will be removed.</DeleteWarning>
          )}
          {onlyVersion && isModelRow && (
            <DeleteWarning>
              It's the folder's only version — the folder stays, but with no file until you add one.
            </DeleteWarning>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Printers section
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// A printer's Moonraker: connection, statistics, maintenance, print history
// ---------------------------------------------------------------------------
const fmtDuration = (s) => {
  if (!s) return "0m";
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return h ? `${h.toLocaleString()}h ${String(m).padStart(2, "0")}m` : `${m}m`;
};
const fmtMetres = (mm) => `${((mm || 0) / 1000).toLocaleString(undefined, { maximumFractionDigits: (mm || 0) >= 100000 ? 0 : 1 })} m`;
const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
const fmtUnix = (s) => (s ? new Date(s * 1000).toLocaleString() : "—");
const headerButton = () => ({
  display: "flex", alignItems: "center", gap: 5, ...ui, fontSize: fs(12), background: "none", color: c.textMuted,
  border: `1px solid ${c.border}`, borderRadius: 3, padding: "0 9px", height: 26, cursor: "pointer", flexShrink: 0,
  textDecoration: "none", boxSizing: "border-box",
});

// The printer's Moonraker as the printer page sees it. On opening a printer: check the connection, show what
// Farmhand already has, then sync the history in the background if the printer answers. `key` restarts all of it
// when the printer or its address changes.
// onSynced: called after each successful sync (the page reloads the printer, whose service hours have moved on)
function useMoonraker(printerId, key, onSynced) {
  const [status, setStatus] = useState(null); // GET /printers/{id}/moonraker
  const [stats, setStats] = useState(null); // GET /printers/{id}/print-stats
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState(null);
  const [syncTick, setSyncTick] = useState(0); // goes up after every sync, so the history list reloads
  const current = useRef(null);

  const sync = async (id = printerId) => {
    setSyncing(true);
    try {
      await syncPrinterHistory(id);
      if (current.current === key) setSyncError(null);
      await onSynced?.();
    } catch (e) {
      if (current.current === key) setSyncError(e.message || String(e));
    }
    try {
      const s = await getPrintStats(id);
      if (current.current === key) setStats(s);
    } catch {
      /* the stats stay as they were */
    }
    if (current.current === key) {
      setSyncing(false);
      setSyncTick((t) => t + 1);
    }
  };

  useEffect(() => {
    if (!printerId) return undefined;
    current.current = key;
    setStatus(null);
    setStats(null);
    setSyncError(null);
    (async () => {
      const [s, st] = await Promise.all([
        getMoonrakerStatus(printerId).catch((e) => ({ reachable: false, error: e.message || String(e) })),
        getPrintStats(printerId).catch(() => null),
      ]);
      if (current.current !== key) return;
      setStatus(s);
      setStats(st);
      if (s.reachable) await sync(printerId);
    })();
    return () => {
      current.current = null;
    };
  }, [key]);

  return { status, stats, syncing, syncError, syncTick, sync: () => sync() };
}

function StatTile({ label, value, hint }) {
  return (
    <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: "10px 12px", background: c.panelAlt, minWidth: 0 }} title={hint}>
      <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, marginBottom: 4 }}>{label}</div>
      <div style={{ ...mono, fontSize: fs(16), color: c.heading, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{value}</div>
    </div>
  );
}

// Connection + the printer's own lifetime statistics, with "Open Mainsail" and "Sync now"
function MoonrakerCard({ printer, mr }) {
  const { status, stats, syncing, syncError } = mr;
  const totals = stats?.totals;
  const archive = stats?.archive;
  let dot = c.textFaint;
  let line = "Checking the connection…";
  if (status) {
    if (status.reachable) {
      const ready = status.klippy_state === "ready";
      dot = ready ? c.green : c.amber;
      line = `Connected${status.klippy_state ? ` · Klipper ${status.klippy_state}` : ""}${status.moonraker_version ? ` · Moonraker ${status.moonraker_version}` : ""}`;
    } else {
      dot = c.danger;
      line = status.error || "Can't reach Moonraker.";
    }
  }
  const failed = archive ? archive.jobs - (archive.by_status.completed || 0) - (archive.by_status.in_progress || 0) - (archive.by_status.cancelled || 0) : 0;
  const lastSync = stats?.last_sync_at || status?.last_sync_at;
  const lastSyncError = syncError || stats?.last_sync_error;

  return (
    <div data-testid="moonraker-card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <div style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>Connection and statistics</div>
        <div style={{ display: "flex", gap: 8 }}>
          {printer.mainsailUrl && (
            <a data-testid="open-mainsail" href={printer.mainsailUrl} target="_blank" rel="noreferrer" style={headerButton()} title={printer.mainsailUrl}>
              <ExternalLink size={12} />
              Open Mainsail
            </a>
          )}
          <button
            data-testid="moonraker-sync"
            onClick={mr.sync}
            disabled={syncing || !status?.reachable}
            title={status?.reachable ? "Copy the printer's latest print history into Farmhand" : "The printer can't be reached right now"}
            style={{ ...headerButton(), opacity: syncing || !status?.reachable ? 0.55 : 1, cursor: syncing || !status?.reachable ? "default" : "pointer" }}
          >
            <RefreshCw size={12} style={syncing ? { animation: "fh-spin 1s linear infinite" } : undefined} />
            {syncing ? "Syncing…" : "Sync now"}
          </button>
        </div>
      </div>
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 14 }}>
        <div data-testid="moonraker-status" style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: status?.reachable ? c.textPrimary : c.textMuted, lineHeight: 1.5 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: dot, flexShrink: 0, marginTop: 6 }} />
          <span>
            {line}
            {status?.reachable && printer.moonrakerUrl && (
              <span style={{ ...mono, fontSize: fs(11), color: c.textFaint, marginLeft: 8 }}>{printer.moonrakerUrl}</span>
            )}
          </span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 8, marginTop: 12 }}>
          <StatTile label="Prints" value={totals ? totals.total_jobs.toLocaleString() : "—"} hint="All jobs the printer has recorded" />
          <StatTile label="Print time" value={totals ? fmtDuration(totals.total_print_time) : "—"} hint="Time spent printing (pauses not counted)" />
          <StatTile label="Filament used" value={totals ? fmtMetres(totals.total_filament_used) : "—"} />
          <StatTile label="Longest print" value={totals ? fmtDuration(totals.longest_print) : "—"} />
        </div>

        <div data-testid="moonraker-sync-state" style={{ ...ui, fontSize: fs(12), color: lastSyncError ? c.amber : c.textFaint, marginTop: 10, lineHeight: 1.6 }}>
          {lastSyncError
            ? `Last sync failed: ${lastSyncError}${lastSync ? ` The figures above are from ${fmtWhen(lastSync)}.` : ""}`
            : lastSync
              ? `Statistics from the printer, as of ${fmtWhen(lastSync)}.`
              : "Not synced yet."}
          {archive && archive.jobs > 0 && (
            <div>
              Farmhand has {archive.jobs.toLocaleString()} print{archive.jobs === 1 ? "" : "s"} on record:{" "}
              {(archive.by_status.completed || 0).toLocaleString()} completed, {(archive.by_status.cancelled || 0).toLocaleString()} cancelled,{" "}
              {failed.toLocaleString()} failed{archive.by_status.in_progress ? `, ${archive.by_status.in_progress} in progress` : ""}.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- energy: per print (from the history) and the whole printer (from the power meter's readings) ----
const fmtKwh = (v) => (v == null ? "—" : `${v.toLocaleString(undefined, { maximumFractionDigits: v < 10 ? 2 : v < 100 ? 1 : 0 })} kWh`);
const periodKey = (d, by) => (by === "year" ? `${d.getFullYear()}` : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
const periodLabel = (key, by) =>
  by === "year" ? key : new Date(Number(key.slice(0, 4)), Number(key.slice(5)) - 1, 1).toLocaleDateString(undefined, { month: "short", year: "numeric" });

// Totals per month or year, in this browser's time zone. Prints: each print's energy, by when it started. Whole
// printer: the meter's rise between one reading and the next, counted in the period of the later reading (a meter
// that went backwards was reset, so its new value is what it used since). The period holding the first reading only
// covers part of it, and is marked so.
function energyByPeriod({ jobs, readings }, by) {
  const rows = {};
  const row = (key) => (rows[key] ??= { key, prints: 0, printCount: 0, whole: null, partial: false });
  jobs.forEach(([at, kwh]) => {
    if (!at) return;
    const r = row(periodKey(new Date(at), by));
    r.prints += kwh;
    r.printCount += 1;
  });
  for (let i = 1; i < readings.length; i++) {
    const [, before] = readings[i - 1];
    const [at, now] = readings[i];
    const r = row(periodKey(new Date(at), by));
    r.whole = (r.whole ?? 0) + (now >= before ? now - before : now);
  }
  if (readings.length) {
    const first = row(periodKey(new Date(readings[0][0]), by));
    first.partial = true;
    first.whole ??= 0;
  }
  return Object.values(rows).sort((a, b) => (a.key < b.key ? 1 : -1)); // newest first
}

function EnergyPanel({ printer, syncTick }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [by, setBy] = useState("month");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let live = true;
    getEnergy(printer.id)
      .then((d) => live && (setData(d), setError(null)))
      .catch((e) => live && setError(e.message || String(e)));
    return () => {
      live = false;
    };
  }, [printer.id, syncTick]);

  const hasAny = data && (data.meter || data.jobs.length > 0);
  const periods = hasAny ? energyByPeriod(data, by) : [];
  const shown = showAll ? periods : periods.slice(0, by === "month" ? 12 : 5);
  const max = Math.max(1e-9, ...periods.map((p) => Math.max(p.prints, p.whole ?? 0)));
  const now = new Date();
  const thisPeriod = periods.find((p) => p.key === periodKey(now, by));
  const printsKwh = data?.print_total_kwh ?? (data ? data.jobs.reduce((s, [, k]) => s + k, 0) : null);
  const cols = "90px minmax(0, 1fr) 100px 110px 60px";

  return (
    <div data-testid="energy-panel">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <div style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>Energy</div>
        {hasAny && (
          <div data-testid="energy-by" style={{ display: "flex", gap: 6 }}>
            {[{ value: "month", label: "By month" }, { value: "year", label: "By year" }].map((o) => (
              <button
                key={o.value}
                onClick={() => {
                  setBy(o.value);
                  setShowAll(false);
                }}
                aria-pressed={by === o.value}
                style={{
                  ...headerButton(), border: `1px solid ${by === o.value ? c.amber : c.border}`,
                  background: by === o.value ? c.amberDim : "none", color: by === o.value ? c.amber : c.textMuted,
                }}
              >
                {o.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 14 }}>
        {error ? (
          <div style={{ ...ui, fontSize: fs(13), color: c.amber }}>Couldn't load energy: {error}</div>
        ) : !data ? (
          <div style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>Loading…</div>
        ) : !hasAny ? (
          <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6 }}>
            No energy figures yet. They appear once the printer has a power meter set up in Moonraker (a [sensor] with an
            energy value and history fields, e.g. a smart plug) and Farmhand has synced it.
          </div>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
              <StatTile
                label="Whole printer (meter)"
                value={fmtKwh(data.meter?.energy_kwh)}
                hint={data.meter ? `${data.meter.sensor}, read ${fmtWhen(data.meter.taken_at)}. Idle time included.` : "No meter reading yet"}
              />
              <StatTile label="Used by prints" value={fmtKwh(printsKwh)} hint="All prints the printer has recorded" />
              <StatTile label={by === "month" ? "This month, prints" : "This year, prints"} value={fmtKwh(thisPeriod?.prints ?? 0)} />
              <StatTile
                label={by === "month" ? "This month, whole printer" : "This year, whole printer"}
                value={thisPeriod?.whole != null ? fmtKwh(thisPeriod.whole) : "—"}
                hint="From the meter readings Farmhand has taken"
              />
            </div>

            <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, marginTop: 12, overflowX: "auto" }}>
              <div style={{ minWidth: 460 }}>
                <div style={{ display: "grid", gridTemplateColumns: cols, gap: 10, padding: "7px 12px", fontSize: fs(11), color: c.textFaint, background: c.panelAlt, borderBottom: `1px solid ${c.border}`, ...ui }}>
                  <div>{by === "month" ? "Month" : "Year"}</div>
                  <div />
                  <div>Prints</div>
                  <div>Whole printer</div>
                  <div>Prints #</div>
                </div>
                {shown.map((p, i) => (
                  <div
                    key={p.key}
                    data-testid="energy-period"
                    data-period={p.key}
                    style={{ display: "grid", gridTemplateColumns: cols, gap: 10, alignItems: "center", padding: "6px 12px", borderTop: i ? `1px solid ${c.border}` : "none" }}
                  >
                    <div style={{ ...ui, fontSize: fs(12), color: c.textPrimary }}>{periodLabel(p.key, by)}</div>
                    <div style={{ position: "relative", height: 10 }}>
                      {p.whole != null && (
                        <div style={{ position: "absolute", inset: 0, width: `${(p.whole / max) * 100}%`, background: c.tealDim, borderRadius: 2 }} />
                      )}
                      <div style={{ position: "absolute", top: 2, bottom: 2, left: 0, width: `${(p.prints / max) * 100}%`, background: c.amber, borderRadius: 2 }} />
                    </div>
                    <div style={{ ...mono, fontSize: fs(12), color: c.textPrimary }}>{fmtKwh(p.prints)}</div>
                    <div style={{ ...mono, fontSize: fs(12), color: p.whole == null ? c.textFaint : c.teal }} title={p.partial ? "Readings started part-way through this period" : undefined}>
                      {p.whole == null ? "—" : `${p.partial ? "≥ " : ""}${fmtKwh(p.whole)}`}
                    </div>
                    <div style={{ ...mono, fontSize: fs(12), color: c.textMuted }}>{p.printCount || ""}</div>
                  </div>
                ))}
                {periods.length > shown.length && (
                  <button
                    onClick={() => setShowAll(true)}
                    style={{ display: "block", width: "100%", padding: "7px 12px", border: "none", borderTop: `1px solid ${c.border}`, background: "none", color: c.textMuted, ...ui, fontSize: fs(12), cursor: "pointer" }}
                  >
                    Show all {periods.length} {by === "month" ? "months" : "years"}
                  </button>
                )}
              </div>
            </div>
            <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginTop: 8, lineHeight: 1.6 }}>
              <span style={{ display: "inline-block", width: 10, height: 6, background: c.amber, borderRadius: 1, marginRight: 5 }} />
              Prints: each print's own energy, from the printer's history.{" "}
              <span style={{ display: "inline-block", width: 10, height: 6, background: c.tealDim, border: `1px solid ${c.teal}`, borderRadius: 1, margin: "0 5px 0 6px" }} />
              Whole printer, idle included: from the power meter readings Farmhand takes
              {data.meter ? ` (since ${new Date(data.meter.first_reading_at).toLocaleDateString()}; “≥” where they began part-way through).` : ", once there are some."}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---- maintenance: lives on the printer, shared with Mainsail ----
const REMINDER_PARTS = [
  { key: "printtime", label: "Print time", unit: "hours" },
  { key: "filament", label: "Filament", unit: "metres" },
  { key: "date", label: "Time passed", unit: "days" },
];
const emptyReminder = () => ({
  type: null,
  filament: { bool: false, value: null },
  printtime: { bool: false, value: null },
  date: { bool: false, value: null },
});

function MaintenanceForm({ initial, onSubmit, onClose, actionLabel }) {
  const [name, setName] = useState(initial?.name || "");
  const [note, setNote] = useState(initial?.note || "");
  const [reminder, setReminder] = useState(() => {
    const r = { ...emptyReminder(), ...(initial?.reminder || {}) };
    REMINDER_PARTS.forEach(({ key }) => (r[key] = { bool: !!r[key]?.bool, value: r[key]?.value ?? null }));
    return r;
  });
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const setPart = (key, change) => setReminder((r) => ({ ...r, [key]: { ...r[key], ...change } }));

  const submit = async () => {
    setErrorMsg(null);
    if (!name.trim()) return setErrorMsg("Give the maintenance a name.");
    if (reminder.type && !REMINDER_PARTS.some(({ key }) => reminder[key].bool)) {
      return setErrorMsg("Pick at least one of print time, filament or days for the reminder.");
    }
    setSubmitting(true);
    try {
      const r = { type: reminder.type };
      REMINDER_PARTS.forEach(({ key }) => {
        const on = !!reminder.type && reminder[key].bool;
        r[key] = { bool: on, value: on ? Number(reminder[key].value) : null };
      });
      await onSubmit({ name: name.trim(), note: note.trim(), reminder: r });
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
      setSubmitting(false);
    }
  };

  const input = { background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, fontSize: fs(13), ...ui };
  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="e.g. Lubricate linear rails" />
      <div style={{ marginBottom: 14 }}>
        <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 5 }}>Note (optional)</div>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          placeholder="What to do, what to use"
          style={{ ...input, width: "100%", boxSizing: "border-box", padding: "8px 10px", resize: "vertical", lineHeight: 1.5 }}
        />
      </div>
      <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 5 }}>Reminder</div>
      <SegmentedToggle
        options={[{ value: "none", label: "No reminder" }, { value: "one-time", label: "Once" }, { value: "repeat", label: "Repeating" }]}
        value={reminder.type || "none"}
        onChange={(v) => setReminder((r) => ({ ...r, type: v === "none" ? null : v }))}
      />
      {reminder.type && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
          <div style={{ ...ui, fontSize: fs(12), color: c.textMuted, lineHeight: 1.5 }}>
            Due when any of these is reached, counted from now{reminder.type === "repeat" ? " and again each time it's done" : ""}:
          </div>
          {REMINDER_PARTS.map(({ key, label, unit }) => (
            <label key={key} style={{ display: "flex", alignItems: "center", gap: 10, ...ui, fontSize: fs(13), color: c.textMuted }}>
              <input type="checkbox" checked={reminder[key].bool} onChange={(e) => setPart(key, { bool: e.target.checked })} style={{ accentColor: c.amber }} />
              <span style={{ width: 90 }}>{label}</span>
              <input
                type="number"
                min="0"
                step="any"
                value={reminder[key].value ?? ""}
                disabled={!reminder[key].bool}
                onChange={(e) => setPart(key, { value: e.target.value === "" ? null : e.target.value })}
                style={{ ...input, width: 100, padding: "5px 8px", opacity: reminder[key].bool ? 1 : 0.5 }}
              />
              <span>{unit}</span>
            </label>
          ))}
        </div>
      )}
      <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, marginBottom: 14, lineHeight: 1.5 }}>
        Saved on the printer, the same way Mainsail keeps its maintenance list, so it shows there too.
      </div>
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel={actionLabel} submitting={submitting} errorMsg={errorMsg} submittingLabel="Saving…" />
    </>
  );
}

// message: replaces the usual "marks it done on the printer" explanation (the 1500-hour service lives in Farmhand)
function PerformMaintenanceForm({ entry, onSubmit, onClose, message }) {
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const submit = async () => {
    setSubmitting(true);
    setErrorMsg(null);
    try {
      await onSubmit({ note: note.trim() });
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
      setSubmitting(false);
    }
  };
  return (
    <>
      <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6, marginBottom: 12 }}>
        {message || (
          <>
            Marks <b style={{ color: c.heading }}>{entry.name}</b> as done on the printer, now. Mainsail will show it as done too.
            {entry.reminder?.type === "repeat" && " Its next round starts counting straight away."}
          </>
        )}
      </div>
      <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 5 }}>What was done (optional)</div>
      <textarea
        data-testid="maintenance-done-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={3}
        autoFocus
        style={{ width: "100%", boxSizing: "border-box", background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, padding: "8px 10px", fontSize: fs(13), ...ui, resize: "vertical", marginBottom: 14 }}
      />
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel="Mark done" submitting={submitting} errorMsg={errorMsg} submittingLabel="Saving…" />
    </>
  );
}

// "12 / 50 hours printed", "3.4 / 10 m of filament", "8 / 30 days"
const checkText = (ch) => {
  const n = (v) => v.toLocaleString(undefined, { maximumFractionDigits: v < 10 ? 1 : 0 });
  const label = { printtime: "hours printed", filament: "m of filament", date: "days" }[ch.kind];
  return `${n(Math.max(0, ch.used))} / ${n(ch.limit)} ${label}`;
};

function MaintenanceRow({ entry, onDone, onEdit, onDelete }) {
  const done = entry.state === "done";
  return (
    <div data-testid="maintenance-row" data-state={entry.state} style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "10px 14px", borderTop: `1px solid ${c.border}` }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ ...ui, fontSize: fs(14), color: done ? c.textMuted : c.heading }}>{entry.name}</span>
          {entry.state === "due" && <Badge tone="danger">due</Badge>}
          {entry.state === "ok" && <Badge tone="green">ok</Badge>}
          {entry.reminder?.type === "repeat" && <Badge>repeats</Badge>}
          {done && <Badge>done {fmtUnix(entry.end_time)}</Badge>}
        </div>
        {entry.note && <div style={{ ...ui, fontSize: fs(12), color: c.textMuted, marginTop: 3, whiteSpace: "pre-wrap" }}>{entry.note}</div>}
        {entry.checks?.length > 0 && (
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
            {entry.checks.map((ch) => (
              <span key={ch.kind} style={{ ...mono, fontSize: fs(11), color: ch.due ? c.danger : c.textFaint }}>
                {checkText(ch)}
              </span>
            ))}
          </div>
        )}
        {done && entry.perform_note && <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginTop: 3 }}>“{entry.perform_note}”</div>}
      </div>
      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
        {!done && (
          <button data-testid="maintenance-done" onClick={onDone} style={{ ...headerButton(), color: entry.state === "due" ? c.amber : c.textMuted, borderColor: entry.state === "due" ? c.amber : c.border }}>
            <Check size={12} />
            Done
          </button>
        )}
        {!done && (
          <button onClick={onEdit} title="Edit" aria-label="Edit" style={{ ...headerButton(), padding: 0, width: 26, justifyContent: "center" }}>
            <Pencil size={12} />
          </button>
        )}
        <TrashButton title="Delete this maintenance entry" onClick={onDelete} />
      </div>
    </div>
  );
}

// The 1500-hour service, kept in Farmhand: due once the printer's synced print time has grown by 1500 hours since
// the count started (its first sync, or the last time this was marked done). Shown whether or not the printer answers.
function ServiceReminder({ printer }) {
  const { refresh } = useData();
  const [dialog, setDialog] = useState(null); // "done" | null
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const s = printer.service;
  const interval = s.interval_hours;
  const since = s.hours_since ?? 0;
  const pct = Math.min(100, (since / interval) * 100);
  const n = (v) => Math.floor(v).toLocaleString();

  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      await setServiceEnabled(printer.id, !s.enabled);
      await refresh();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  let text;
  if (s.state === "waiting") text = "Starts counting once the printer's print time has been synced.";
  else if (s.state === "off") text = `Switched off for this printer. ${n(since)} print hours since it was last reset.`;
  else text = `${n(since)} / ${n(interval)} print hours since ${s.last_done ? "the last service" : "counting started"}${s.started_at ? ` (${new Date(s.started_at).toLocaleDateString()})` : ""}.`;

  return (
    <div data-testid="service-reminder" data-state={s.state}>
    <div style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "10px 14px" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ ...ui, fontSize: fs(14), color: s.state === "off" ? c.textMuted : c.heading }}>{n(interval)}-hour service</span>
          {s.state === "due" && <Badge tone="danger">due</Badge>}
          {s.state === "ok" && <Badge tone="green">ok</Badge>}
          {s.state === "off" && <Badge>off</Badge>}
          <Badge>repeats · kept in Farmhand</Badge>
        </div>
        <div style={{ ...mono, fontSize: fs(11), color: s.state === "due" ? c.danger : c.textFaint, marginTop: 4 }}>{text}</div>
        {(s.state === "ok" || s.state === "due") && (
          <div style={{ height: 4, borderRadius: 2, background: c.panelAlt, marginTop: 6, maxWidth: 320, overflow: "hidden" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: s.state === "due" ? c.danger : c.teal }} />
          </div>
        )}
        {s.last_done && (
          <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginTop: 4 }}>
            Last done {new Date(s.last_done.done_at).toLocaleDateString()}, after {n(s.last_done.hours)} hours{s.last_done.note ? ` — “${s.last_done.note}”` : ""}
          </div>
        )}
        {error && <div style={{ ...ui, fontSize: fs(12), color: c.amber, marginTop: 4 }}>{error}</div>}
      </div>
      {s.state !== "waiting" && (
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          {s.enabled && (
            <button
              data-testid="service-done"
              onClick={() => setDialog("done")}
              style={{ ...headerButton(), color: s.state === "due" ? c.amber : c.textMuted, borderColor: s.state === "due" ? c.amber : c.border }}
            >
              <Check size={12} />
              Done
            </button>
          )}
          <button data-testid="service-toggle" onClick={toggle} disabled={busy} style={{ ...headerButton(), opacity: busy ? 0.55 : 1 }}>
            {s.enabled ? "Turn off" : "Turn on"}
          </button>
        </div>
      )}
    </div>
      <div data-testid="service-notes" style={{ padding: "0 14px 12px" }}>
        <NotesSection
          key={printer.id}
          kind="service"
          ownerId={printer.id}
          saved={s.notes}
          rev={s.notes_revision}
          updatedAt={s.notes_updated_at}
          onSave={({ notes, baseRevision }) => saveServiceNotes({ printerId: printer.id, notes, baseRevision })}
          description={`About this printer's ${n(interval)}-hour service: what it involves, parts to have ready.`}
          placeholder="Nothing written yet. Notes you add here are kept in Farmhand with this printer's service."
        />
      </div>
      {dialog === "done" && (
        <Modal title={`${n(interval)}-hour service done`} onClose={() => setDialog(null)} width={440}>
          <PerformMaintenanceForm
            entry={{ name: `the ${n(interval)}-hour service`, reminder: { type: null } }}
            message={`The next ${n(interval)} print hours count from the printer's print time now. This is kept in Farmhand, not on the printer.`}
            onClose={() => setDialog(null)}
            onSubmit={async ({ note }) => {
              await serviceDone(printer.id, { note });
              await refresh();
            }}
          />
        </Modal>
      )}
    </div>
  );
}

// onDueCount(n): told how many reminders are due (the 1500-hour service included), for the folded group's heading
function MaintenanceSection({ printer, reachable, onDueCount }) {
  const [data, setData] = useState(null); // { entries, totals }
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null); // { kind: "add" | "edit" | "done" | "delete", entry }
  const [showDone, setShowDone] = useState(false);

  const load = async () => {
    try {
      setData(await getMaintenance(printer.id));
      setError(null);
    } catch (e) {
      setError(e.message || String(e));
    }
  };
  useEffect(() => {
    setData(null);
    setError(null);
    setShowDone(false);
    if (reachable) load();
  }, [printer.id, reachable]);

  const entries = data?.entries || [];
  const order = { due: 0, ok: 1, no_reminder: 2 };
  const open = entries.filter((e) => e.state !== "done").sort((a, b) => order[a.state] - order[b.state]);
  const done = entries.filter((e) => e.state === "done");
  const dueCount = open.filter((e) => e.state === "due").length + (printer.service.state === "due" ? 1 : 0);
  const close = () => setDialog(null);
  useEffect(() => {
    onDueCount?.(dueCount);
  }, [dueCount]);

  return (
    <div data-testid="maintenance-section">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(13), color: c.textFaint }}>
          Maintenance
          {dueCount > 0 && <Badge tone="danger">{dueCount} due</Badge>}
        </div>
        <button
          data-testid="maintenance-add"
          onClick={() => setDialog({ kind: "add" })}
          disabled={!reachable || !data}
          style={{ ...headerButton(), opacity: reachable && data ? 1 : 0.55, cursor: reachable && data ? "pointer" : "default" }}
        >
          <Wrench size={12} />
          Add maintenance
        </button>
      </div>
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel }}>
        <ServiceReminder printer={printer} />
        <div style={{ borderTop: `1px solid ${c.border}` }}>
        {!reachable ? (
          <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, padding: 14, lineHeight: 1.6 }}>
            The rest of the maintenance is kept on the printer (shared with Mainsail), so it shows once the printer can be reached.
          </div>
        ) : error ? (
          <div style={{ ...ui, fontSize: fs(13), color: c.amber, padding: 14 }}>Couldn't load maintenance: {error}</div>
        ) : !data ? (
          <div style={{ ...ui, fontSize: fs(13), color: c.textFaint, padding: 14 }}>Loading…</div>
        ) : entries.length === 0 ? (
          <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, padding: 14 }}>No other maintenance recorded on this printer yet.</div>
        ) : (
          <div style={{ marginTop: -1 }}>
            {open.map((e) => (
              <MaintenanceRow
                key={e.id}
                entry={e}
                onDone={() => setDialog({ kind: "done", entry: e })}
                onEdit={() => setDialog({ kind: "edit", entry: e })}
                onDelete={() => setDialog({ kind: "delete", entry: e })}
              />
            ))}
            {done.length > 0 && (
              <button
                data-testid="maintenance-show-done"
                onClick={() => setShowDone(!showDone)}
                style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", textAlign: "left", padding: "8px 14px", border: "none", borderTop: `1px solid ${c.border}`, background: "none", color: c.textMuted, ...ui, fontSize: fs(12), cursor: "pointer" }}
              >
                <ChevronRight size={12} style={{ transform: showDone ? "rotate(90deg)" : "none" }} />
                {showDone ? "Hide" : "Show"} {done.length} done
              </button>
            )}
            {showDone && done.map((e) => <MaintenanceRow key={e.id} entry={e} onDelete={() => setDialog({ kind: "delete", entry: e })} />)}
          </div>
        )}
        </div>
      </div>

      {dialog?.kind === "add" && (
        <Modal title="Add maintenance" onClose={close} width={480}>
          <MaintenanceForm actionLabel="Add" onClose={close} onSubmit={async (v) => setData(await addMaintenance(printer.id, v))} />
        </Modal>
      )}
      {dialog?.kind === "edit" && (
        <Modal title="Edit maintenance" onClose={close} width={480}>
          <MaintenanceForm
            initial={dialog.entry}
            actionLabel="Save"
            onClose={close}
            onSubmit={async (v) => setData(await updateMaintenance(printer.id, dialog.entry.id, v))}
          />
        </Modal>
      )}
      {dialog?.kind === "done" && (
        <Modal title="Maintenance done" onClose={close} width={440}>
          <PerformMaintenanceForm entry={dialog.entry} onClose={close} onSubmit={async (v) => setData(await performMaintenance(printer.id, dialog.entry.id, v))} />
        </Modal>
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog title="Delete maintenance" onClose={close} onConfirm={async () => setData(await deleteMaintenance(printer.id, dialog.entry.id))}>
          Delete <b style={{ color: c.heading }}>{dialog.entry.name}</b> from the printer? It's removed from Mainsail too. This can't be undone.
        </ConfirmDialog>
      )}
    </div>
  );
}

// ---- print history: Farmhand's copy ----
const JOB_STATUS_TONE = { completed: "green", in_progress: "teal", cancelled: "muted" };
const JOB_FILTERS = [
  { value: "", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];
const HISTORY_PAGE = 25;

// open / onToggle: whether the list is folded away (only its heading and count show then)
function PrintHistory({ printer, syncTick, open = true, onToggle }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const ask = useRef(0);

  const load = async (offset) => {
    const mine = ++ask.current;
    setLoading(true);
    try {
      const r = await getPrintJobs(printer.id, { limit: HISTORY_PAGE, offset, status, q });
      if (mine !== ask.current) return;
      setJobs((prev) => (offset ? [...prev, ...r.jobs] : r.jobs));
      setTotal(r.total);
      setError(null);
    } catch (e) {
      if (mine === ask.current) setError(e.message || String(e));
    } finally {
      if (mine === ask.current) setLoading(false);
    }
  };
  useEffect(() => {
    const t = setTimeout(() => load(0), q ? 250 : 0); // a short pause while typing
    return () => clearTimeout(t);
  }, [printer.id, status, q, syncTick]);

  const control = { background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, fontSize: fs(13), ...ui };
  const cols = "minmax(140px, 170px) minmax(200px, 1fr) 100px 90px 80px 80px"; // below ~730px wide the table scrolls sideways
  return (
    <div data-testid="print-history">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: open ? 10 : 0, flexWrap: "wrap" }}>
        <SectionToggle open={open} onToggle={onToggle} controlsId="print-history-body" testId="toggle-history">
          Print history
          {total != null && <span style={{ color: c.textFaint }}>({total.toLocaleString()} {total === 1 ? "print" : "prints"})</span>}
        </SectionToggle>
        {open && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            data-testid="print-history-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search file names…"
            aria-label="Search print history"
            style={{ ...control, padding: "5px 9px", width: 200 }}
          />
          <select data-testid="print-history-filter" value={status} onChange={(e) => setStatus(e.target.value)} style={{ ...control, padding: "5px 8px" }}>
            {JOB_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
        )}
      </div>
      <div id="print-history-body" style={{ display: open ? "block" : "none", border: `1px solid ${c.border}`, borderRadius: 4, overflowX: "auto", background: c.panel }}>
        <div style={{ minWidth: 730 }}>
        <div style={{ display: "grid", gridTemplateColumns: cols, gap: 10, padding: "7px 14px", fontSize: fs(11), color: c.textFaint, background: c.panelAlt, borderBottom: `1px solid ${c.border}`, ...ui }}>
          <div>Started</div>
          <div>File</div>
          <div>Status</div>
          <div>Print time</div>
          <div>Filament</div>
          <div>Energy</div>
        </div>
        {error && <div style={{ ...ui, fontSize: fs(13), color: c.amber, padding: 14 }}>Couldn't load the history: {error}</div>}
        {!error && jobs.length === 0 && (
          <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, padding: 14 }}>
            {loading ? "Loading…" : q || status ? "No prints match." : "No print history yet. It's copied from the printer when it can be reached."}
          </div>
        )}
        {jobs.map((j, i) => (
          <div
            key={j.id}
            data-testid="print-job"
            data-status={j.status}
            style={{ display: "grid", gridTemplateColumns: cols, gap: 10, alignItems: "center", padding: "7px 14px", borderTop: i ? `1px solid ${c.border}` : "none" }}
          >
            <div style={{ ...mono, fontSize: fs(12), color: c.textMuted }}>{fmtWhen(j.start_time)}</div>
            <div style={{ ...mono, fontSize: fs(12), color: c.textPrimary, overflowWrap: "anywhere" }} title={j.filename}>
              {j.filename}
            </div>
            <div>
              <Badge tone={JOB_STATUS_TONE[j.status] || "danger"}>{j.status.replace(/_/g, " ")}</Badge>
            </div>
            <div style={{ ...mono, fontSize: fs(12), color: c.textMuted }}>{fmtDuration(j.print_duration)}</div>
            <div style={{ ...mono, fontSize: fs(12), color: c.textMuted }}>{fmtMetres(j.filament_used)}</div>
            <div
              style={{ ...mono, fontSize: fs(12), color: j.energy_kwh == null ? c.textFaint : c.textMuted }}
              title={j.avg_power_w != null ? `Average ${Math.round(j.avg_power_w)} W${j.max_power_w != null ? `, peak ${Math.round(j.max_power_w)} W` : ""}` : undefined}
            >
              {j.energy_kwh == null ? "—" : fmtKwh(j.energy_kwh)}
            </div>
          </div>
        ))}
        {total != null && jobs.length < total && (
          <button
            data-testid="print-history-more"
            onClick={() => load(jobs.length)}
            disabled={loading}
            style={{ display: "block", width: "100%", padding: "8px 14px", border: "none", borderTop: `1px solid ${c.border}`, background: "none", color: c.textMuted, ...ui, fontSize: fs(12), cursor: loading ? "default" : "pointer" }}
          >
            {loading ? "Loading…" : `Show ${Math.min(HISTORY_PAGE, total - jobs.length)} more`}
          </button>
        )}
        </div>
      </div>
    </div>
  );
}

function AddPrinterForm({ onClose }) {
  const { refresh } = useData();
  const [name, setName] = useState("");
  const [kind, setKind] = useState("");
  const [wiredIp, setWiredIp] = useState("");
  const [wirelessIp, setWirelessIp] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!name.trim()) return setErrorMsg("A printer needs a name.");
    setSubmitting(true);
    try {
      await createPrinter({ name: name.trim(), kind: kind.trim(), wiredIp: wiredIp.trim(), wirelessIp: wirelessIp.trim() });
      await refresh();
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="Must match the printer profile name inside your 3MF files exactly" />
      <TextField label="Type (optional)" value={kind} onChange={setKind} placeholder="e.g. Prusa MK4 (OctoPrint)" />
      <TextField label="Wired IP (optional)" value={wiredIp} onChange={setWiredIp} placeholder="e.g. 10.0.6.21" />
      <TextField label="Wireless IP (optional)" value={wirelessIp} onChange={setWirelessIp} placeholder="e.g. 10.0.6.121" />
      <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, marginBottom: 14, lineHeight: 1.5 }}>
        The name is the printer's unique key, and it's what a 3MF upload is matched against — it has to be spelled exactly like the printer profile your slicer put in the file (including capitalization and spaces).
      </div>
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel="Add printer" submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}

function EditPrinterForm({ printer, onClose }) {
  const { refresh, bundlesForPrinter } = useData();
  const [name, setName] = useState(printer.name);
  const [kind, setKind] = useState(printer.kind || "");
  const [wiredIp, setWiredIp] = useState(printer.wired || "");
  const [wirelessIp, setWirelessIp] = useState(printer.wireless || "");
  const [decommissioned, setDecommissioned] = useState(!!printer.decommissioned);
  const [moonrakerUrl, setMoonrakerUrl] = useState(printer.moonrakerUrlOverride || "");
  const [apiKey, setApiKey] = useState(""); // blank = keep whatever is saved
  const [removeKey, setRemoveKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const hasFiles = bundlesForPrinter(printer.id).length > 0;
  const ip = wiredIp.trim() || wirelessIp.trim();

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!name.trim()) return setErrorMsg("A printer needs a name.");
    setSubmitting(true);
    try {
      await updatePrinter(printer.id, {
        name: name.trim(),
        kind: kind.trim(),
        wiredIp: wiredIp.trim(),
        wirelessIp: wirelessIp.trim(),
        decommissioned,
        moonrakerUrl: moonrakerUrl.trim(),
        moonrakerApiKey: removeKey ? "" : apiKey.trim() || undefined,
      });
      await refresh();
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="Unique printer name" />
      <TextField label="Type" value={kind} onChange={setKind} placeholder="e.g. Prusa MK4 (OctoPrint)" />
      <TextField label="Wired IP" value={wiredIp} onChange={setWiredIp} placeholder="e.g. 10.0.6.21" />
      <TextField label="Wireless IP" value={wirelessIp} onChange={setWirelessIp} placeholder="e.g. 10.0.6.121" />
      <TextField
        label="Moonraker address (optional)"
        value={moonrakerUrl}
        onChange={setMoonrakerUrl}
        placeholder={ip ? `Leave blank to use http://${ip}:7125` : "Add an IP above, or give the address here"}
      />
      <TextField
        label="Moonraker API key (optional)"
        type="password"
        value={apiKey}
        onChange={(v) => {
          setApiKey(v);
          if (v) setRemoveKey(false);
        }}
        disabled={removeKey}
        placeholder={printer.hasMoonrakerApiKey ? "A key is saved. Type a new one to replace it." : "Only needed if Moonraker asks for one"}
      />
      {printer.hasMoonrakerApiKey && (
        <label style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(13), color: c.textMuted, marginTop: -6, marginBottom: 14, cursor: "pointer" }}>
          <input type="checkbox" checked={removeKey} onChange={(e) => setRemoveKey(e.target.checked)} style={{ accentColor: c.amber }} />
          Remove the saved API key
        </label>
      )}
      <label style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(13), color: c.textMuted, marginBottom: 14, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={decommissioned}
          onChange={(e) => setDecommissioned(e.target.checked)}
          style={{ accentColor: c.amber }}
        />
        Decommissioned (retired — kept for its history, but not offered for new uploads)
      </label>
      {hasFiles && name.trim() !== printer.name && (
        <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, marginBottom: 14, lineHeight: 1.5 }}>
          Renaming is safe for the files already here: they stay locked to this printer, and files sliced under the old
          name will still be matched to it.
        </div>
      )}
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel="Save" submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}

// Searching the 3MF files on one printer: like the Models search, every word has to be found, in any of the file's
// names (every version), the models it was sliced from, its slicer, or its notes.
function bundleMatches(bundle, models, words) {
  if (words.length === 0) return true;
  const haystack = [
    ...bundle.versions.map((v) => v.filename || ""),
    ...models.map((m) => m.name),
    bundle.slicer || "",
    bundle.notes || "",
  ].join("\n").toLowerCase();
  return words.every((w) => haystack.includes(w));
}

const PRINTER_SORT_KEY = "farmhand.printerSort";

// Which parts of a printer page are folded away: { moonraker, threemf, history } (true = folded). The same on every
// printer, remembered in this browser; all start folded until opened.
// (The key changed when "folded" became the start, so sections left open under the old default start folded again.)
const PRINTER_SECTIONS_KEY = "farmhand.printerSections.v2";
function usePrinterSections() {
  const [folded, setFolded] = useState(() => {
    try {
      const v = JSON.parse(localStorage.getItem(PRINTER_SECTIONS_KEY));
      return v && typeof v === "object" && !Array.isArray(v) ? v : {};
    } catch {
      return {};
    }
  });
  const isFolded = (state, name) => state[name] !== false; // folded unless opened
  const toggle = (name) =>
    setFolded((prev) => {
      const next = { ...prev, [name]: !isFolded(prev, name) };
      try {
        localStorage.setItem(PRINTER_SECTIONS_KEY, JSON.stringify(next));
      } catch {
        /* storage unavailable: it just isn't remembered */
      }
      return next;
    });
  return { isOpen: (name) => !isFolded(folded, name), toggle };
}

// A section heading that folds the section away or opens it again
function SectionToggle({ open, onToggle, controlsId, testId, children }) {
  return (
    <button
      data-testid={testId}
      aria-expanded={open}
      aria-controls={controlsId}
      onClick={onToggle}
      title={open ? "Fold away" : "Show"}
      style={{ display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", padding: 0, cursor: "pointer", ...ui, fontSize: fs(13), color: open ? c.textFaint : c.textMuted, textAlign: "left" }}
    >
      <ChevronRight size={14} style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform 0.12s ease", flexShrink: 0 }} />
      {children}
    </button>
  );
}

function PrintersSection({ path, setPath, compareSelection, toggleCompareSelect }) {
  const { printers, bundlesForPrinter, modelsForPrinter, versionsByBundle, modelsForBundle, refresh } = useData();
  const view = path[1]; // {printerId}
  const expansion = useBundleExpansion();
  const [addPrinterOpen, setAddPrinterOpen] = useState(false);
  const [editPrinterOpen, setEditPrinterOpen] = useState(false);
  const [query, setQuery] = useState(""); // the search for this printer's 3MF files
  const searchRef = useRef(null);
  // The printer list's order by name ("asc" A→Z | "desc" Z→A), remembered in this browser
  const [printerSort, setPrinterSortState] = useState(() => {
    try {
      return localStorage.getItem(PRINTER_SORT_KEY) === "desc" ? "desc" : "asc";
    } catch {
      return "asc";
    }
  });
  const setPrinterSort = (dir) => {
    setPrinterSortState(dir);
    try {
      localStorage.setItem(PRINTER_SORT_KEY, dir);
    } catch {
      /* storage unavailable: it just isn't remembered */
    }
  };

  useEffect(() => {
    setQuery(""); // a fresh search for each printer
  }, [view?.printerId]);

  const sections = usePrinterSections();
  const [maintenanceDue, setMaintenanceDue] = useState(0); // reported by the maintenance list, for when it's folded

  // The open printer's Moonraker; starts over if its address or API key changes
  const viewed = view ? printers.find((p) => p.id === view.printerId) : null;
  const mr = useMoonraker(viewed?.id, viewed ? `${viewed.id}|${viewed.moonrakerUrl}|${viewed.hasMoonrakerApiKey}` : null, refresh);

  if (!view) {
    return (
      <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 14 }}>
        <button
          onClick={() => setAddPrinterOpen(true)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            ...ui,
            fontSize: fs(13),
            background: "none",
            color: c.textMuted,
            border: `1px solid ${c.border}`,
            borderRadius: 4,
            padding: "7px 12px",
            cursor: "pointer",
          }}
        >
          <Printer size={13} />
          Add printer
        </button>
      </div>
      {addPrinterOpen && (
        <Modal title="Add printer" onClose={() => setAddPrinterOpen(false)}>
          <AddPrinterForm onClose={() => setAddPrinterOpen(false)} />
        </Modal>
      )}
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 140px 140px 90px",
            padding: "8px 16px",
            fontSize: fs(12),
            color: c.textFaint,
            borderBottom: `1px solid ${c.border}`,
            background: c.panelAlt,
          }}
        >
          <button
            data-testid="printer-sort-name"
            onClick={() => setPrinterSort(printerSort === "asc" ? "desc" : "asc")}
            title={printerSort === "asc" ? "Sorted A→Z — click for Z→A" : "Sorted Z→A — click for A→Z"}
            aria-label={printerSort === "asc" ? "Name, sorted A to Z. Click to reverse" : "Name, sorted Z to A. Click to reverse"}
            style={{ display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", padding: 0, color: c.textMuted, cursor: "pointer", ...ui, fontSize: fs(12), justifySelf: "start" }}
          >
            Name
            {printerSort === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
          </button>
          <div>Type</div>
          <div>Wired IP</div>
          <div>Wireless IP</div>
          <div>Status</div>
        </div>
        {[...printers].sort((a, b) => (printerSort === "desc" ? -1 : 1) * nameCollator.compare(a.name, b.name)).map((p) => {
          const bCount = bundlesForPrinter(p.id).length;
          return (
            <Row key={p.id} onClick={() => setPath([{ label: "Printers" }, { printerId: p.id }])}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr 140px 140px 90px",
                  width: "100%",
                  alignItems: "center",
                }}
              >
                <div style={{ ...ui, fontSize: fs(14), color: c.heading, display: "flex", alignItems: "center", gap: 8 }}>
                  <Printer size={15} color={c.textFaint} />
                  {p.name}
                  {bCount > 0 && <Lock size={12} color={c.textFaint} />}
                  {p.notes && (
                    <span data-testid="printer-has-notes" title={`Has notes: ${p.notes.slice(0, 120)}${p.notes.length > 120 ? "…" : ""}`} style={{ display: "flex" }}>
                      <StickyNote size={13} color={c.textFaint} />
                    </span>
                  )}
                  {p.service.state === "due" && (
                    <span data-testid="printer-service-due" title={`${Math.floor(p.service.hours_since).toLocaleString()} print hours since the last service`}>
                      <Badge tone="danger">
                        <Wrench size={11} />
                        {p.service.interval_hours.toLocaleString()} h service due
                      </Badge>
                    </span>
                  )}
                </div>
                <div style={{ ...ui, fontSize: fs(13), color: c.textMuted }}>{p.kind}</div>
                <div style={{ ...mono, fontSize: fs(12), color: p.wired ? c.textPrimary : c.textFaint, display: "flex", alignItems: "center", gap: 6 }}>
                  {p.wired && <Cable size={12} color={c.teal} />}
                  {p.wired || "—"}
                </div>
                <div style={{ ...mono, fontSize: fs(12), color: p.wireless ? c.heading : c.textFaint, display: "flex", alignItems: "center", gap: 6 }}>
                  {p.wireless && <Wifi size={12} color={c.textFaint} />}
                  {p.wireless || "—"}
                </div>
                <div>
                  {p.decommissioned ? <Badge>decommissioned</Badge> : <Badge tone="green">active</Badge>}
                </div>
              </div>
            </Row>
          );
        })}
      </div>
      </div>
    );
  }

  const printer = printers.find((p) => p.id === view.printerId);
  const allBundles = [...bundlesForPrinter(printer.id)].sort(newestFirst);
  const words = searchWords(query);
  const searching = words.length > 0;
  const pBundles = allBundles.filter((b) => bundleMatches(b, modelsForBundle(b), words));
  const modelCount = modelsForPrinter(printer.id).length;
  const control = { background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, fontSize: fs(13), ...ui };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
      {editPrinterOpen && (
        <Modal title="Edit printer" onClose={() => setEditPrinterOpen(false)}>
          <EditPrinterForm printer={printer} onClose={() => setEditPrinterOpen(false)} />
        </Modal>
      )}
      {/* searches this printer's 3MF files (listed further down); at the top so it's the first thing to hand */}
      {allBundles.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <div style={{ position: "relative", flex: "1 1 320px", maxWidth: 460 }}>
            <Search size={15} color={c.textFaint} style={{ position: "absolute", left: 11, top: 10, pointerEvents: "none" }} />
            <input
              ref={searchRef}
              data-testid="printer-3mf-search"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  if (query) setQuery("");
                  else e.currentTarget.blur();
                }
              }}
              placeholder={`Search 3MF files on ${printer.name}…`}
              aria-label={`Search 3MF files on ${printer.name}`}
              autoComplete="off"
              spellCheck={false}
              style={{ ...control, width: "100%", boxSizing: "border-box", padding: "8px 34px 8px 34px" }}
            />
            {query && (
              <button
                data-testid="printer-3mf-search-clear"
                onClick={() => {
                  setQuery("");
                  searchRef.current?.focus();
                }}
                aria-label="Clear search"
                title="Clear search (Esc)"
                style={{ position: "absolute", right: 6, top: 6, width: 24, height: 24, display: "flex", alignItems: "center", justifyContent: "center", background: "none", border: "none", color: c.textMuted, cursor: "pointer", padding: 0 }}
              >
                <X size={14} />
              </button>
            )}
          </div>
          {searching && (
            <span data-testid="printer-3mf-count" style={{ ...ui, fontSize: fs(12), color: c.textFaint }}>
              {pBundles.length} of {allBundles.length} 3MF files
            </span>
          )}
        </div>
      )}
      <div>
        <SectionLabel>Printer</SectionLabel>
        <div
          style={{
            border: `1px solid ${c.border}`,
            borderRadius: 4,
            padding: 14,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            background: c.panel,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: 4,
                border: `1px solid ${c.border}`,
                background: c.panelAlt,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Printer size={26} color={c.teal} strokeWidth={1.4} />
            </div>
            <div>
              <div style={{ ...ui, fontSize: fs(15), color: c.heading, display: "flex", alignItems: "center", gap: 8 }}>
                {printer.name}
                {allBundles.length > 0 && <Lock size={13} color={c.textFaint} />}
              </div>
              <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, marginTop: 3 }}>{printer.kind}</div>
              <div style={{ display: "flex", gap: 14, marginTop: 8 }}>
                <div style={{ ...mono, fontSize: fs(12), color: printer.wired ? c.textPrimary : c.textFaint, display: "flex", alignItems: "center", gap: 5 }}>
                  <Cable size={12} color={printer.wired ? c.teal : c.textFaint} />
                  {printer.wired || "—"}
                </div>
                <div style={{ ...mono, fontSize: fs(12), color: printer.wireless ? c.heading : c.textFaint, display: "flex", alignItems: "center", gap: 5 }}>
                  <Wifi size={12} color={c.textFaint} />
                  {printer.wireless || "—"}
                </div>
              </div>
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5, alignItems: "flex-end", flexShrink: 0 }}>
            <button
              onClick={() => setEditPrinterOpen(true)}
              style={{ display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 4, padding: "5px 10px", cursor: "pointer", marginBottom: 3 }}
            >
              <Pencil size={12} />
              Edit
            </button>
            {printer.decommissioned ? <Badge>decommissioned</Badge> : <Badge tone="green">active</Badge>}
            <Badge tone="teal">{allBundles.length} 3MF</Badge>
            <Badge tone="teal">{modelCount} Models</Badge>
          </div>
        </div>
      </div>

      <PrinterNotes key={printer.id} printer={printer} />

      {/* Everything from the printer's Moonraker, foldable as one. Folded, it stays mounted (just hidden), so it
          keeps what it loaded and can still say if maintenance is due. */}
      <div data-testid="moonraker-group">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: sections.isOpen("moonraker") ? 14 : 0, flexWrap: "wrap" }}>
          <SectionToggle open={sections.isOpen("moonraker")} onToggle={() => sections.toggle("moonraker")} controlsId="moonraker-body" testId="toggle-moonraker">
            Moonraker: connection, energy and maintenance
          </SectionToggle>
          {!sections.isOpen("moonraker") && (
            <>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(12), color: c.textFaint }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: !mr.status ? c.textFaint : mr.status.reachable ? c.green : c.danger }} />
                {!mr.status ? "checking…" : mr.status.reachable ? "connected" : "not reachable"}
              </span>
              {maintenanceDue > 0 && <Badge tone="danger">{maintenanceDue} maintenance due</Badge>}
            </>
          )}
        </div>
        <div id="moonraker-body" style={{ display: sections.isOpen("moonraker") ? "flex" : "none", flexDirection: "column", gap: 28 }}>
          <MoonrakerCard printer={printer} mr={mr} />
          <EnergyPanel printer={printer} syncTick={mr.syncTick} />
          <MaintenanceSection printer={printer} reachable={!!mr.status?.reachable} onDueCount={setMaintenanceDue} />
        </div>
      </div>

      <div data-testid="threemf-group">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: sections.isOpen("threemf") ? 10 : 0 }}>
          <SectionToggle open={sections.isOpen("threemf")} onToggle={() => sections.toggle("threemf")} controlsId="threemf-body" testId="toggle-threemf">
            3MF files on {printer.name}
            <span style={{ color: c.textFaint }}>({allBundles.length})</span>
          </SectionToggle>
          {sections.isOpen("threemf") && <VersionsToggleAll bundleList={pBundles} expansion={expansion} />}
        </div>
        {sections.isOpen("threemf") && (
        <div id="threemf-body">
        {searching && pBundles.length === 0 && (
          <div data-testid="printer-3mf-search-empty" style={{ ...ui, fontSize: fs(13), color: c.textMuted, padding: "12px 4px", lineHeight: 1.7 }}>
            No 3MF files on {printer.name} match <b style={{ color: c.heading }}>“{query.trim()}”</b>. Every word has to match a file name, a model, the slicer or the notes.{" "}
            <button
              onClick={() => setQuery("")}
              style={{ ...ui, fontSize: fs(13), background: "none", border: "none", color: c.amber, textDecoration: "underline", cursor: "pointer", padding: 0 }}
            >
              Clear search
            </button>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {pBundles.map((b) => {
            const vlist = versionsByBundle[b.id] || [];
            const latest = vlist[0];
            const rest = vlist.slice(1);
            const isExpanded = expansion.isExpanded(b.id, vlist.length);
            const mods = modelsForBundle(b);
            const isSelected = vlist.some((v) => compareSelection.includes(v.id)); // any of its versions picked
            return (
              <div
                key={b.id}
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
                    style={{ display: "flex", flexDirection: "column", gap: 4, cursor: rest.length > 0 ? "pointer" : "default", minWidth: 0 }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                      <FileBox size={15} color={c.textFaint} />
                      <EditableName
                        value={b.name}
                        label="this 3MF file" extension=".3mf" boxed
                        testId="bundle-name"
                        textStyle={{ ...mono, fontSize: fs(13) }}
                        onSave={(name) => renameBundleVersion(b.versions[0].id, name)}
                      >
                        <span style={{ ...mono, fontSize: fs(13), color: "inherit" }}><Highlighted text={b.name} words={words} /></span>
                      </EditableName>
                      <Badge>{b.slicer}</Badge>
                    </div>
                    <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, paddingLeft: 23 }}>
                      from <Highlighted text={mods.map((m) => m.name).join(" + ")} words={words} />
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                    <span style={{ ...ui, fontSize: fs(12), color: c.textFaint }}>
                      {vlist.length} version{vlist.length === 1 ? "" : "s"}
                    </span>
                    {rest.length > 0 && (
                      <VersionsToggle open={isExpanded} olderCount={rest.length} controlsId={`versions-${b.id}`} onToggle={() => expansion.set(b.id, !isExpanded)} />
                    )}
                    <NewVersionButton bundle={b} />
                    <DeleteBundleButton bundle={b} />
                  </div>
                </div>
                {latest && <VersionRow ver={latest} isLatest showFileStatus bundle={b} compareSelection={compareSelection} onToggleCompare={toggleCompareSelect} />}
                <div id={`versions-${b.id}`}>
                  {isExpanded && rest.map((v) => <VersionRow key={v.v} ver={v} showFileStatus bundle={b} compareSelection={compareSelection} onToggleCompare={toggleCompareSelect} />)}
                </div>
                <BundleNotes key={b.id} bundle={b} />
              </div>
            );
          })}
        </div>
        </div>
        )}
      </div>

      <PrintHistory printer={printer} syncTick={mr.syncTick} open={sections.isOpen("history")} onToggle={() => sections.toggle("history")} />
    </div>
  );
}

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
    return <div style={{ ...mono, fontSize: fs(12), color: c.textFaint, wordBreak: "break-word", paddingTop: 2 }}>{formatVal(settings[k])}</div>;
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
      style={{
        ...mono,
        fontSize: fs(12),
        color: s.fg,
        background: s.soft,
        padding: "2px 7px",
        borderRadius: 3,
        justifySelf: "start",
        maxWidth: "100%",
        maxHeight: 160,
        overflow: "auto",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
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

function DiffView({ left, right, onClose }) {
  // left / right are { bundle, version }: exactly the two versions that were picked
  const { versionLabel } = useData();
  const leftLabel = versionLabel(left);
  const rightLabel = versionLabel(right);
  const [onlyDiffs, setOnlyDiffs] = useState(false);
  const [leftSettings, setLeftSettings] = useState(null);
  const [rightSettings, setRightSettings] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [cursor, setCursor] = useState(-1); // which difference the Previous/Next buttons are on
  const rowRefs = useRef({});

  useEffect(() => {
    let cancelled = false;
    setLeftSettings(null);
    setRightSettings(null);
    setLoadError(null);
    setCursor(-1);
    Promise.all([fetchVersionSettings(left.version.id), fetchVersionSettings(right.version.id)])
      .then(([l, r]) => {
        if (!cancelled) {
          setLeftSettings(l);
          setRightSettings(r);
        }
      })
      .catch((e) => !cancelled && setLoadError(e.message || String(e)));
    return () => {
      cancelled = true;
    };
  }, [left.version.id, right.version.id]);

  if (loadError) {
    return <div style={{ ...ui, fontSize: fs(13), color: c.amber, padding: 16 }}>Couldn't load settings: {loadError}</div>;
  }
  if (!leftSettings || !rightSettings) {
    return <div style={{ ...ui, fontSize: fs(13), color: c.textFaint, padding: 16 }}>Loading settings…</div>;
  }

  const allKeys = Array.from(new Set([...Object.keys(leftSettings), ...Object.keys(rightSettings)]));
  const categoryOrder = [
    "Layers & Perimeters", "Infill", "Support Material", "Skirt & Brim", "Speed", "Kinematics",
    "Retraction", "Temperature", "Cooling", "Filament", "Printer", "Custom G-code", "Other Settings",
  ];
  const grouped = {};
  allKeys.forEach((key) => {
    const cat = categorizeKey(key);
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(key);
  });
  categoryOrder.forEach((cat) => grouped[cat]?.sort());

  // A setting differs if its value differs, or if only one of the two files has it at all. This compares the
  // EXACT text: formatVal() shortens long values for display, and comparing the shortened text would call two
  // long values (a start G-code edited near its end, say) identical.
  const exactText = (settings, key) => (key in settings ? String(settings[key] ?? "") : null);
  const differsAt = (key) => exactText(leftSettings, key) !== exactText(rightSettings, key);

  const diffKeys = []; // in the order they appear on screen
  categoryOrder.forEach((cat) => (grouped[cat] || []).forEach((key) => differsAt(key) && diffKeys.push(key)));
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
        <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.5 }}>
          Comparing <span style={{ color: c.amber, fontWeight: 600 }}>{leftLabel}</span>{" "}
          (left) against <span style={{ color: c.teal, fontWeight: 600 }}>{rightLabel}</span> (right)
          <div data-testid="diff-summary" style={{ color: c.textFaint }}>
            {allKeys.length} settings,{" "}
            <span style={{ color: diffCount ? c.amber : c.textFaint, fontWeight: diffCount ? 600 : 400 }}>{diffCount} differ</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button data-testid="diff-prev" onClick={() => goTo(cursor < 0 ? diffCount - 1 : cursor - 1)} disabled={!diffCount} style={stepButton}>
            <ArrowUp size={12} />
            Previous
          </button>
          <button data-testid="diff-next" onClick={() => goTo(cursor + 1)} disabled={!diffCount} style={stepButton}>
            <ArrowDown size={12} />
            Next difference
          </button>
          <span data-testid="diff-position" style={{ ...mono, fontSize: fs(11), color: c.textFaint, minWidth: 54 }}>
            {diffCount ? (cursor >= 0 ? `${cursor + 1} of ${diffCount}` : `${diffCount} total`) : ""}
          </span>
          <label style={{ display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(12), color: c.textMuted, cursor: "pointer", flexShrink: 0 }}>
            <input type="checkbox" checked={onlyDiffs} onChange={(e) => setOnlyDiffs(e.target.checked)} style={{ accentColor: c.amber }} />
            Only show differences
          </label>
        </div>
      </div>

      {diffCount === 0 && (
        <div data-testid="diff-identical" style={{ ...ui, fontSize: fs(13), color: c.textMuted, padding: "14px 16px", borderBottom: `1px solid ${c.border}` }}>
          These two versions have identical settings.
        </div>
      )}

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
                <span style={{ ...ui, fontSize: fs(12), color: c.textFaint, textTransform: "uppercase", letterSpacing: 0.4 }}>{cat}</span>
                {catDiffs > 0 ? (
                  <span data-testid="diff-category-count"><Badge tone="amber">{catDiffs} of {keys.length} differ</Badge></span>
                ) : (
                  <span style={{ ...ui, fontSize: fs(11), color: c.textFaint }}>no differences</span>
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
                {visibleKeys.map((key, i) => {
                  const differs = differsAt(key);
                  const isCurrent = diffKeys[cursor] === key;
                  return (
                    <div
                      key={key}
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
                        borderTop: i === 0 ? "none" : `1px solid ${c.border}`,
                        borderLeft: `3px solid ${differs ? c.amber : "transparent"}`,
                        background: differs ? `${c.amber}14` : "transparent", // a faint wash across the whole row
                        outline: isCurrent ? `2px solid ${c.amber}` : "none",
                        outlineOffset: -2,
                      }}
                    >
                      <div
                        style={{ ...ui, fontSize: fs(13), color: differs ? c.textPrimary : c.textFaint, fontWeight: differs ? 500 : 400, paddingTop: 2, minWidth: 0, overflowWrap: "break-word" }}
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
                })}
              </div>
            </div>
          );
        })}
      </div>
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
function SettingsViewer({ bundle, ver }) {
  const [settings, setSettings] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setSettings(null);
    setLoadError(null);
    fetchVersionSettings(ver.id)
      .then((s) => !cancelled && setSettings(s))
      .catch((e) => !cancelled && setLoadError(e.message || String(e)));
    return () => {
      cancelled = true;
    };
  }, [ver.id]);

  if (loadError) {
    return <div style={{ ...ui, fontSize: fs(13), color: c.amber }}>Couldn't load settings: {loadError}</div>;
  }
  if (!settings) {
    return <div style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>Loading settings…</div>;
  }

  return <SettingsBrowser bundle={bundle} ver={ver} settings={settings} />;
}

function SettingsBrowser({ bundle, ver, settings }) {
  const keys = Object.keys(settings);

  const grouped = {};
  keys.forEach((key) => {
    const { tab, section } = classifyPrusa(key);
    grouped[tab] = grouped[tab] || {};
    grouped[tab][section] = grouped[tab][section] || [];
    grouped[tab][section].push(key);
  });
  Object.values(grouped).forEach((sections) => {
    Object.values(sections).forEach((list) => list.sort());
  });

  const tabsWithContent = Object.keys(PRUSA_SECTIONS).filter((t) => grouped[t]);
  const [activeTab, setActiveTab] = useState(tabsWithContent[0] || "Print Settings");
  const currentSections = (PRUSA_SECTIONS[activeTab] || []).filter((s) => grouped[activeTab]?.[s]?.length);
  const [activeSection, setActiveSection] = useState(currentSections[0]);
  const effectiveSection = currentSections.includes(activeSection) ? activeSection : currentSections[0];
  const rows = grouped[activeTab]?.[effectiveSection] || [];

  return (
    <div>
      <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 12 }}>
        {bundle.name} · v{ver.v} · {keys.length} settings
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
              <span style={{ ...mono, fontSize: fs(10), color: c.textFaint, marginLeft: 6 }}>
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
              <div style={{ ...ui, fontSize: fs(13), color: c.textMuted }} title={key}>
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

// ---------------------------------------------------------------------------
// Models section
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Upload — real, wired to the API. STL/OBJ/STEP go to the library; a 3MF
// needs a source model + a printer (auto-detected from the file). gcode
// is optional — it doesn't have to be on hand at upload time.
// ---------------------------------------------------------------------------
function Modal({ title, onClose, children, width = 420 }) {
  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width,
          maxWidth: "90vw",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          background: c.panel,
          border: `1px solid ${c.borderStrong}`,
          borderRadius: 6,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 16px",
            borderBottom: `1px solid ${c.border}`,
            flexShrink: 0,
          }}
        >
          <div style={{ ...ui, fontSize: fs(14), color: c.heading, fontWeight: 600 }}>{title}</div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: c.textFaint, cursor: "pointer", padding: 2 }}
          >
            <X size={16} />
          </button>
        </div>
        <div style={{ padding: 16, overflow: "auto" }}>{children}</div>
      </div>
    </div>
  );
}

function Dropzone({ label, compact = false, onFile, file, accept }) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  // Matching against `accept` ourselves: browsers don't enforce the
  // input's accept attribute on a programmatic drop, only on the native
  // file picker, so a dropped file needs the same check applied by hand.
  const accepts = (filename) => {
    if (!accept) return true;
    const exts = accept.split(",").map((s) => s.trim().toLowerCase());
    const name = filename.toLowerCase();
    return exts.some((ext) => name.endsWith(ext));
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };
  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (!dropped) return;
    if (!accepts(dropped.name)) return;
    onFile?.(dropped);
  };

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={handleDragOver}
      onDragEnter={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        border: `1.5px dashed ${isDragging ? c.amber : file ? c.teal : c.borderStrong}`,
        borderRadius: 4,
        padding: compact ? "14px 16px" : "26px 16px",
        textAlign: "center",
        color: file ? c.textPrimary : c.textFaint,
        background: isDragging ? c.amberDim : "transparent",
        ...ui,
        fontSize: fs(13),
        marginBottom: 14,
        display: "flex",
        flexDirection: compact ? "row" : "column",
        alignItems: "center",
        justifyContent: "center",
        gap: compact ? 8 : 0,
        cursor: "pointer",
        transition: "background 0.1s ease, border-color 0.1s ease",
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={(e) => onFile?.(e.target.files?.[0] || null)}
        style={{ display: "none" }}
      />
      <Upload size={compact ? 14 : 20} color={isDragging ? c.amber : file ? c.teal : c.textFaint} style={{ marginBottom: compact ? 0 : 8 }} />
      <div>{file ? file.name : isDragging ? "Drop it" : label}</div>
    </div>
  );
}

function FieldSelect({ label, options, placeholder, value, onChange }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 5 }}>{label}</div>
      <select
        value={value ?? ""}
        onChange={(e) => onChange?.(e.target.value)}
        style={{
          width: "100%",
          background: c.panelAlt,
          border: `1px solid ${c.border}`,
          borderRadius: 4,
          color: c.textPrimary,
          padding: "8px 10px",
          fontSize: fs(13),
          ...ui,
        }}
      >
        <option value="" disabled>
          {placeholder}
        </option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function ModalActions({ onClose, onSubmit, actionLabel, submitting, errorMsg, submittingLabel = "Uploading…" }) {
  return (
    <div>
      {errorMsg && (
        <div style={{ ...ui, fontSize: fs(12), color: c.amber, marginBottom: 10, lineHeight: 1.5 }}>{errorMsg}</div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
        <button
          onClick={onClose}
          disabled={submitting}
          style={{
            ...ui,
            fontSize: fs(13),
            background: "none",
            color: c.textMuted,
            border: `1px solid ${c.border}`,
            borderRadius: 3,
            padding: "7px 14px",
            cursor: submitting ? "default" : "pointer",
          }}
        >
          Cancel
        </button>
        <button
          onClick={onSubmit}
          disabled={submitting}
          style={{
            ...ui,
            fontSize: fs(13),
            background: c.amber,
            color: c.onAccent,
            border: "none",
            borderRadius: 3,
            padding: "7px 14px",
            fontWeight: 600,
            cursor: submitting ? "default" : "pointer",
            opacity: submitting ? 0.7 : 1,
          }}
        >
          {submitting ? submittingLabel : actionLabel}
        </button>
      </div>
    </div>
  );
}

function SegmentedToggle({ options, value, onChange }) {
  return (
    <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          style={{
            ...ui,
            fontSize: fs(12),
            padding: "6px 12px",
            borderRadius: 4,
            cursor: "pointer",
            border: `1px solid ${value === o.value ? c.amber : c.border}`,
            background: value === o.value ? c.amberDim : "transparent",
            color: value === o.value ? c.amber : c.textMuted,
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function TextField({ label, value, onChange, placeholder, type = "text", disabled = false }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 5 }}>{label}</div>
      <input
        type={type}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={type === "password" ? "new-password" : "off"}
        style={{
          width: "100%",
          background: c.panelAlt,
          border: `1px solid ${c.border}`,
          borderRadius: 4,
          color: c.textPrimary,
          padding: "8px 10px",
          fontSize: fs(13),
          opacity: disabled ? 0.6 : 1,
          ...ui,
        }}
      />
    </div>
  );
}

// presetModel: when set (uploading from inside a specific STL folder), the
// source-model choice and printer field are both skipped — the bundle
// attaches to the current folder, and the printer is read from the 3MF's own
// embedded profile reference rather than asked for.
function Upload3mfForm({ presetModel, onClose }) {
  const { sourceModels, printers, bundles, modelsForBundle, refresh } = useData();
  const [mode, setMode] = useState("existing"); // "existing" | "new"
  const [newName, setNewName] = useState("");
  const [newStlFile, setNewStlFile] = useState(null);
  const [existingModelId, setExistingModelId] = useState("");
  const [threemfFile, setThreemfFile] = useState(null);
  const [gcodeFile, setGcodeFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  // What the 3MF says about its own printer, from the backend (null until a file is dropped)
  const [inspecting, setInspecting] = useState(false);
  const [inspection, setInspection] = useState(null); // { printerProfileName, slicer, matchedPrinter }
  const [inspectError, setInspectError] = useState(null);
  const [printerChoice, setPrinterChoice] = useState("create"); // "create" | "existing"
  const [existingPrinterId, setExistingPrinterId] = useState("");
  const inspectSeq = useRef(0);
  const [versionChoice, setVersionChoice] = useState(null); // null = take the default; "new"; or the id of an entry

  // Is this a newer version of something already there? Two signals, both only on the file's own printer
  // (matched from the file, so an entry's printer lock can't object):
  //   * an entry that already has a file with THIS FILE NAME — the usual way to publish an update is to
  //     re-slice and upload under the same name, and that holds whichever model is picked below
  //   * an entry for the model being added to
  const targetModelId = presetModel ? presetModel.id : mode === "existing" && existingModelId ? Number(existingModelId) : null;
  const matchedPrinterId = inspection?.matchedPrinter?.id ?? null;
  const fileName = (threemfFile?.name || "").toLowerCase();
  const onPrinter = matchedPrinterId ? bundles.filter((b) => b.printerId === matchedPrinterId) : [];
  const byFileName = fileName ? onPrinter.filter((b) => b.versions.some((v) => (v.filename || "").toLowerCase() === fileName)).sort(newestFirst) : [];
  const byModel = targetModelId
    ? onPrinter.filter((b) => b.sourceModelIds.includes(targetModelId) && !byFileName.includes(b)).sort(newestFirst)
    : [];
  const candidates = [...byFileName, ...byModel];
  const defaultChoice = candidates.length ? String(candidates[0].id) : "new";
  const stillValid = versionChoice === "new" || candidates.some((b) => String(b.id) === versionChoice);
  const choice = stillValid && versionChoice ? versionChoice : defaultChoice;
  const versionTarget = candidates.find((b) => String(b.id) === choice) || null;

  // Decommissioned printers shouldn't be offered as a home for new files
  const selectablePrinters = printers.filter((p) => !p.decommissioned);

  const handleThreemfFile = async (file) => {
    setThreemfFile(file);
    setInspection(null);
    setInspectError(null);
    setErrorMsg(null);
    if (!file) return;
    const seq = ++inspectSeq.current; // ignore stale results if another file is dropped meanwhile
    setInspecting(true);
    try {
      const result = await inspectThreemf(file);
      if (seq !== inspectSeq.current) return;
      setInspection(result);
      // Sensible default: create the file's printer if it has one, else pick an existing one
      setPrinterChoice(result.printerProfileName ? "create" : "existing");
      setExistingPrinterId("");
    } catch (e) {
      if (seq !== inspectSeq.current) return;
      setInspectError(e.message || String(e));
    } finally {
      if (seq === inspectSeq.current) setInspecting(false);
    }
  };

  const needsPrinterDecision = inspection && !inspection.matchedPrinter;
  const canCreatePrinter = !!inspection?.printerProfileName;

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!threemfFile) return setErrorMsg("Drop a .3mf file first.");
    if (inspecting) return setErrorMsg("Still reading the 3MF — one moment.");
    if (inspectError) return setErrorMsg("This 3MF couldn't be read, so it can't be uploaded.");
    if (versionTarget) {
      // A newer version of an existing entry: nothing new to create, the printer is already matched
      setSubmitting(true);
      try {
        await addBundleVersion({ bundleId: versionTarget.id, threemf: threemfFile, gcode: gcodeFile });
        await refresh();
        onClose();
      } catch (e) {
        setErrorMsg(e.message || String(e));
      } finally {
        setSubmitting(false);
      }
      return;
    }

    if (!presetModel) {
      if (mode === "existing" && !existingModelId) return setErrorMsg("Pick a source model.");
      if (mode === "new" && !newName.trim()) return setErrorMsg("Give the new STL folder a name.");
    }
    if (needsPrinterDecision && printerChoice === "existing" && !existingPrinterId) {
      return setErrorMsg("Pick which printer this file belongs to.");
    }

    setSubmitting(true);
    try {
      let sourceModelIds;
      if (presetModel) {
        sourceModelIds = [presetModel.id];
      } else if (mode === "existing") {
        sourceModelIds = [Number(existingModelId)];
      } else {
        const created = await createSourceModel({ name: newName.trim(), file: newStlFile || undefined });
        sourceModelIds = [created.id];
        // If a later step fails, a retry should reuse this folder, not create a second one
        await refresh();
        setMode("existing");
        setExistingModelId(String(created.id));
      }

      let printerId;
      if (inspection?.matchedPrinter) {
        printerId = inspection.matchedPrinter.id;
      } else if (printerChoice === "create" && canCreatePrinter) {
        // Named exactly as the file's own profile, so future uploads for it auto-match.
        // (Reuse it if an earlier attempt already created it before failing.)
        const already = printers.find((p) => p.name === inspection.printerProfileName);
        if (already) {
          printerId = already.id;
        } else {
          const printer = await createPrinter({ name: inspection.printerProfileName });
          printerId = printer.id;
          await refresh();
          setInspection((prev) => ({ ...prev, matchedPrinter: normalizePrinter(printer) }));
        }
      } else {
        printerId = Number(existingPrinterId);
      }

      await createBundle({ sourceModelIds, threemf: threemfFile, gcode: gcodeFile, printerId });
      await refresh();
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Dropzone label="Drop the .3mf file here" file={threemfFile} onFile={handleThreemfFile} accept=".3mf" />
      <Dropzone label="Drop the matching .gcode file here (optional)" file={gcodeFile} onFile={setGcodeFile} accept=".gcode,.gco" />

      {/* Printer — read from the file, with a way out when it isn't registered */}
      {inspecting && (
        <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 14 }}>Reading the 3MF…</div>
      )}
      {inspectError && (
        <div style={{ ...ui, fontSize: fs(12), color: c.amber, marginBottom: 14, lineHeight: 1.5 }}>
          Couldn't read this 3MF: {inspectError}
        </div>
      )}
      {inspection?.matchedPrinter && (
        <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 14 }}>
          Printer: <span style={{ color: c.heading }}>{inspection.matchedPrinter.name}</span> — detected from the file.
        </div>
      )}
      {needsPrinterDecision && (
        <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 14, background: c.panelAlt }}>
          <div style={{ ...ui, fontSize: fs(12), color: c.textMuted, marginBottom: 10, lineHeight: 1.5 }}>
            {canCreatePrinter ? (
              <>
                This file was sliced for <span style={{ color: c.heading }}>“{inspection.printerProfileName}”</span>, which
                isn't registered yet.
              </>
            ) : (
              <>This file doesn't say which printer it was sliced for.</>
            )}
          </div>

          {canCreatePrinter && selectablePrinters.length > 0 && (
            <SegmentedToggle
              value={printerChoice}
              onChange={setPrinterChoice}
              options={[
                { value: "create", label: `Create “${inspection.printerProfileName}”` },
                { value: "existing", label: "Use an existing printer" },
              ]}
            />
          )}

          {canCreatePrinter && printerChoice === "create" && (
            <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, lineHeight: 1.5 }}>
              A printer named exactly “{inspection.printerProfileName}” will be added to the registry, and this file
              will be locked to it. You can fill in its type and IP addresses later.
            </div>
          )}

          {(printerChoice === "existing" || !canCreatePrinter) &&
            (selectablePrinters.length > 0 ? (
              <FieldSelect
                label="Printer"
                placeholder="Select a printer…"
                value={existingPrinterId}
                onChange={setExistingPrinterId}
                options={selectablePrinters.map((p) => ({ value: String(p.id), label: p.name }))}
              />
            ) : (
              <div style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.5 }}>
                There are no registered printers to choose from yet — add one under Printers first.
              </div>
            ))}
        </div>
      )}

      {presetModel ? (
        <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 14 }}>
          Adding to <span style={{ color: c.heading }}>{presetModel.name}</span>.
        </div>
      ) : (
        <>
          <SegmentedToggle
            value={mode}
            onChange={setMode}
            options={[
              { value: "existing", label: "Existing STL folder" },
              { value: "new", label: "New STL folder" },
            ]}
          />
          {mode === "existing" ? (
            <FieldSelect
              label="Source model"
              placeholder="Select a source model…"
              value={existingModelId}
              onChange={setExistingModelId}
              options={sourceModels.map((m) => ({ value: String(m.id), label: m.name }))}
            />
          ) : (
            <>
              <TextField
                label="New STL folder name"
                value={newName}
                onChange={setNewName}
                placeholder="e.g. MMMini_NewCreature_v01.stl"
              />
              {sourceModels.some((m) => m.name.toLowerCase() === newName.trim().toLowerCase()) && newName.trim() && (
                <div data-testid="folder-exists" style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.5, marginTop: -6, marginBottom: 14 }}>
                  A folder called “{newName.trim()}” already exists.{" "}
                  <button
                    onClick={() => {
                      const existing = sourceModels.find((m) => m.name.toLowerCase() === newName.trim().toLowerCase());
                      setMode("existing");
                      setExistingModelId(String(existing.id));
                    }}
                    style={{ ...ui, fontSize: fs(12), background: "none", border: "none", color: c.amber, textDecoration: "underline", cursor: "pointer", padding: 0 }}
                  >
                    Use that folder instead
                  </button>
                </div>
              )}
              <Dropzone
                label="Optionally drop the STL / OBJ / STEP file here — the folder can be created without one"
                compact
                file={newStlFile}
                onFile={setNewStlFile}
                accept=".stl,.obj,.step,.stp"
              />
            </>
          )}
        </>
      )}

      {candidates.length > 0 && (
        <div data-testid="version-choice" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 14, background: c.panelAlt }}>
          <div style={{ ...ui, fontSize: fs(12), color: c.textMuted, lineHeight: 1.5, marginBottom: 8 }}>
            {byFileName.length > 0 ? (
              <>
                <span style={{ color: c.heading }}>{inspection.matchedPrinter.name}</span> already has{" "}
                {byFileName.length === 1 ? "a 3MF" : `${byFileName.length} 3MF files`} with this file name.
              </>
            ) : (
              <>
                This model already has {candidates.length === 1 ? "a 3MF" : `${candidates.length} 3MF files`} on{" "}
                <span style={{ color: c.heading }}>{inspection.matchedPrinter.name}</span>.
              </>
            )}{" "}
            Is this file a newer version of {candidates.length === 1 ? "it" : "one of them"}?
          </div>
          {candidates.map((b) => (
            <label key={b.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, marginBottom: 6, cursor: "pointer" }}>
              <input type="radio" name="version-target" checked={choice === String(b.id)} onChange={() => setVersionChoice(String(b.id))} style={{ accentColor: c.amber, marginTop: 3 }} />
              <span>
                New version of <span style={mono}>{b.name}</span>{" "}
                <span style={{ color: c.textFaint }}>
                  — now v{b.versions[0]?.v}
                  {!presetModel && modelsForBundle(b).length > 0 ? `, on ${modelsForBundle(b).map((m) => m.name).join(", ")}` : ""}
                </span>
              </span>
            </label>
          ))}
          <label style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, cursor: "pointer" }}>
            <input type="radio" name="version-target" checked={choice === "new"} onChange={() => setVersionChoice("new")} style={{ accentColor: c.amber, marginTop: 3 }} />
            <span>A separate 3MF (keep it independent of the others)</span>
          </label>
          {versionTarget && (
            <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, marginTop: 8 }}>
              It becomes v{(versionTarget.versions[0]?.v || 0) + 1} and is shown above the older versions.
            </div>
          )}
        </div>
      )}

      <ModalActions
        onClose={onClose}
        onSubmit={handleSubmit}
        actionLabel={versionTarget ? "Add as new version" : "Upload"}
        submitting={submitting || inspecting}
        errorMsg={errorMsg}
      />
    </>
  );
}

function UploadStlForm({ onClose }) {
  const { refresh, sourceModels } = useData();
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [choice, setChoice] = useState(null); // null = take the default; "new"; or the id of an existing model
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const handleFile = (f) => {
    setFile(f);
    if (f && !name) setName(f.name);
  };

  // A file with the same name as a model already in the library is most likely a newer version of it
  // (the usual way to publish an update is to export over the same file name and upload it again).
  const wanted = (name.trim() || file?.name || "").toLowerCase();
  const matches = wanted
    ? sourceModels
        .filter((m) => m.name.toLowerCase() === wanted)
        .sort((x, y) => (Date.parse(y.created) || 0) - (Date.parse(x.created) || 0) || y.id - x.id)
    : [];
  const picked = choice === "new" || matches.some((m) => String(m.id) === choice) ? choice : null;
  const effective = picked ?? (matches.length ? String(matches[0].id) : "new");
  const target = matches.find((m) => String(m.id) === effective) || null;

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!file) return setErrorMsg("Choose an STL / OBJ / STEP file first.");
    if (!name.trim()) return setErrorMsg("Give it a name.");
    setSubmitting(true);
    try {
      if (target) await addSourceModelVersion({ modelId: target.id, file, note: note.trim() });
      else await createSourceModel({ name: name.trim(), file });
      await refresh();
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Dropzone label="Drop a source model file here, or click to browse" file={file} onFile={handleFile} accept=".stl,.obj,.step,.stp" />
      <TextField label="Name" value={name} onChange={setName} placeholder="e.g. MMMini_NewCreature_v01.stl" />
      {matches.length > 0 && (
        <div data-testid="stl-version-choice" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 14, background: c.panelAlt }}>
          <div style={{ ...ui, fontSize: fs(12), color: c.textMuted, lineHeight: 1.5, marginBottom: 8 }}>
            {matches.length === 1 ? "A model" : `${matches.length} models`} called{" "}
            <span style={{ color: c.heading }}>{matches[0].name}</span> {matches.length === 1 ? "is" : "are"} already in the
            library. Is this a newer version of {matches.length === 1 ? "it" : "one of them"}?
          </div>
          {matches.map((m) => (
            <label key={m.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, marginBottom: 6, cursor: "pointer" }}>
              <input type="radio" name="stl-version-target" checked={effective === String(m.id)} onChange={() => setChoice(String(m.id))} style={{ accentColor: c.amber, marginTop: 3 }} />
              <span>
                New version of <span style={mono}>{m.name}</span>{" "}
                <span style={{ color: c.textFaint }}>— now v{m.versions[0]?.v || 0}</span>
              </span>
            </label>
          ))}
          <label style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, cursor: "pointer" }}>
            <input type="radio" name="stl-version-target" checked={effective === "new"} onChange={() => setChoice("new")} style={{ accentColor: c.amber, marginTop: 3 }} />
            <span>A separate model (keep it independent)</span>
          </label>
          {target && (
            <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, marginTop: 8 }}>
              It becomes v{(target.versions[0]?.v || 0) + 1} and is shown above the older versions.
            </div>
          )}
        </div>
      )}
      {target && <TextField label="What changed? (optional)" value={note} onChange={setNote} placeholder="e.g. thicker legs" />}
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel={target ? "Add as new version" : "Add to library"} submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Models list: sorting, layout, and redrawing previews
// ---------------------------------------------------------------------------
function useMediaQuery(query) {
  const read = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false);
  const [matches, setMatches] = useState(read);
  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

// Each option's `dir` is the natural direction when it's first picked (newest first, most first, A→Z)
const MODEL_SORTS = [
  { key: "name", label: "Name", dir: "asc" },
  { key: "added", label: "Date added", dir: "desc" },
  { key: "threemf", label: "3MF files", dir: "desc" },
  { key: "printers", label: "Printers", dir: "desc" },
  { key: "type", label: "Type", dir: "asc" },
];
const SORT_STORAGE_KEY = "farmhand.modelSort";
const PENDING_CONFIG_KEY = "farmhand.configPending"; // changes not yet confirmed by the server
const nameCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" }); // "Part 2" before "Part 10"

// Anything unrecognised (an old or hand-edited value) becomes the default
function normalizeModelSort(saved) {
  if (MODEL_SORTS.some((o) => o.key === saved?.key) && (saved.dir === "asc" || saved.dir === "desc")) {
    return { key: saved.key, dir: saved.dir };
  }
  return { key: "name", dir: "asc" };
}

// What this browser remembers: shown straight away, then replaced by the server's copy when that arrives
function loadModelSort() {
  try {
    return normalizeModelSort(JSON.parse(localStorage.getItem(SORT_STORAGE_KEY)));
  } catch {
    return normalizeModelSort(null);
  }
}

function saveModelSort(sort) {
  try {
    localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify(sort));
  } catch {
    /* storage unavailable: the choice just won't be remembered */
  }
}

// rows: [{ m, bundleCount, printerCount }]. Ties always fall back to name A→Z, so the order is stable.
function sortModelRows(rows, { key, dir }) {
  const sign = dir === "desc" ? -1 : 1;
  const byName = (a, b) => nameCollator.compare(a.m.name, b.m.name) || a.m.id - b.m.id;
  const primary = {
    name: (a, b) => nameCollator.compare(a.m.name, b.m.name),
    added: (a, b) => (Date.parse(a.m.created) || 0) - (Date.parse(b.m.created) || 0) || a.m.id - b.m.id,
    threemf: (a, b) => a.bundleCount - b.bundleCount,
    printers: (a, b) => a.printerCount - b.printerCount,
    type: (a, b) => nameCollator.compare(a.m.type, b.m.type),
  }[key];
  return [...rows].sort((a, b) => sign * primary(a, b) || byName(a, b));
}

// Which 3MF entries show all their versions. By default an entry shows just its newest version, with a toggle for
// the older ones. Only entries someone has explicitly opened or closed are remembered (in this browser). Shared by
// the model page and the printer page, so opening an entry on one opens it on the other too.
// (The key changed when "hidden" became the default for every entry, so choices made under the old default reset.)
const EXPANSION_KEY = "farmhand.bundleExpanded.v2";
function readExpansion() {
  try {
    const v = JSON.parse(localStorage.getItem(EXPANSION_KEY));
    return v && typeof v === "object" && !Array.isArray(v) ? v : {};
  } catch {
    return {};
  }
}
function useBundleExpansion() {
  const { bundles } = useData();
  const [explicit, setExplicit] = useState(readExpansion);
  const isExpanded = (id) => explicit[id] === true; // older versions start hidden
  const apply = (changes) =>
    setExplicit((prev) => {
      const live = new Set(bundles.map((b) => String(b.id)));
      const next = {};
      Object.entries({ ...prev, ...changes }).forEach(([id, open]) => {
        if (live.has(String(id)) && typeof open === "boolean") next[id] = open; // forget entries that no longer exist
      });
      try {
        localStorage.setItem(EXPANSION_KEY, JSON.stringify(next));
      } catch {
        /* storage unavailable: it just isn't remembered */
      }
      return next;
    });
  return {
    isExpanded,
    set: (id, open) => apply({ [id]: open }),
    setMany: (ids, open) => apply(Object.fromEntries(ids.map((id) => [id, open]))),
  };
}

// Shows or hides an entry's older versions — a button in its header, beside "New version"
function VersionsToggle({ open, olderCount, onToggle, controlsId }) {
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
function VersionsToggleAll({ bundleList, expansion }) {
  const withOlder = bundleList.filter((b) => b.versions.length > 1);
  if (withOlder.length === 0) return null;
  const anyOpen = withOlder.some((b) => expansion.isExpanded(b.id, b.versions.length));
  return (
    <button
      data-testid="versions-toggle-all"
      onClick={() => expansion.setMany(withOlder.map((b) => b.id), !anyOpen)}
      style={{
        display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(12), background: "none", color: c.textMuted,
        border: `1px solid ${c.border}`, borderRadius: 4, padding: "5px 10px", cursor: "pointer", marginBottom: 10,
      }}
    >
      <ChevronRight size={12} style={{ transform: anyOpen ? "rotate(90deg)" : "none" }} />
      {anyOpen ? "Collapse all versions" : "Expand all versions"}
    </button>
  );
}

// Entries (3MFs) under a printer: the one updated most recently first
const newestFirst = (a, b) => (Date.parse(b.updated) || 0) - (Date.parse(a.updated) || 0) || b.id - a.id;

// ---- notes about a model ----
const NOTES_MAX = 20000;
// (kind "service": the notes kept with a printer's 1500-hour service, so its id is the printer's)
const NOTES_STORAGE = {
  printer: { draft: "farmhand.printerNotesDraft", collapsed: "farmhand.printerNotesCollapsed.v2" },
  bundle: { draft: "farmhand.bundleNotesDraft", collapsed: "farmhand.bundleNotesCollapsed.v2" },
  service: { draft: "farmhand.serviceNotesDraft", collapsed: "farmhand.serviceNotesCollapsed" },
  model: { draft: "farmhand.notesDraft", collapsed: "farmhand.notesCollapsed.v2" },
};
const draftKey = (kind, id) => `${(NOTES_STORAGE[kind] || NOTES_STORAGE.model).draft}.${id}`;
function readDraft(kind, id) {
  try {
    const d = JSON.parse(localStorage.getItem(draftKey(kind, id)));
    if (d && typeof d.text === "string" && Number.isInteger(d.base)) return d;
  } catch {
    /* no draft, or storage unavailable */
  }
  return null;
}
function writeDraft(kind, id, draft) {
  try {
    if (draft) localStorage.setItem(draftKey(kind, id), JSON.stringify(draft));
    else localStorage.removeItem(draftKey(kind, id));
  } catch {
    /* storage unavailable: the draft just isn't kept */
  }
}

// Whether a model's, printer's or 3MF's notes are folded down to their first line. Every one STARTS folded; opening
// or closing one is remembered for that model/printer/3MF, in this browser. Anything unreadable means folded.
// (The keys changed when folding went from two lines to one, so notes left open before that start folded again.)
const notesCollapsedKey = (kind) => (NOTES_STORAGE[kind] || NOTES_STORAGE.model).collapsed;
function readNotesCollapsed(kind, id) {
  try {
    const choice = JSON.parse(localStorage.getItem(notesCollapsedKey(kind)))?.[id];
    return typeof choice === "boolean" ? choice : true;
  } catch {
    return true;
  }
}
function writeNotesCollapsed(kind, id, collapsed) {
  try {
    let all = JSON.parse(localStorage.getItem(notesCollapsedKey(kind)));
    if (!all || typeof all !== "object" || Array.isArray(all)) all = {};
    all[id] = collapsed;
    localStorage.setItem(notesCollapsedKey(kind), JSON.stringify(all));
  } catch {
    /* storage unavailable: it just isn't remembered */
  }
}

// Free-text notes about a model or a printer. Typed text is protected three ways: it's kept as a draft in this
// browser if you leave or reload, the browser asks before a tab with unsaved notes is closed, and a save that
// would overwrite what someone else saved meanwhile is stopped. One component serves both, so they behave
// identically: `kind` ("model" | "printer") keeps their drafts apart, `onSave({ notes, baseRevision })` does the saving.
function NotesSection({ kind, ownerId, saved, rev, updatedAt, onSave, description, placeholder }) {
  const { refresh } = useData();

  const [startDraft] = useState(() => {
    const d = readDraft(kind, ownerId);
    return d && d.text !== saved ? d : null; // a draft identical to what's saved is no draft
  });
  const [text, setText] = useState(startDraft ? startDraft.text : saved);
  const [base, setBase] = useState(startDraft ? startDraft.base : rev); // the revision this text was written from
  const [restored, setRestored] = useState(!!startDraft);
  const [phase, setPhase] = useState("idle"); // idle | saving | error
  const [error, setError] = useState(null);
  const [conflict, setConflict] = useState(null); // { notes, revision, updatedAt }: what someone else saved meanwhile
  const synced = useRef(saved); // the saved text this editor last matched
  const areaRef = useRef(null);
  const [collapsed, setCollapsedState] = useState(() => readNotesCollapsed(kind, ownerId));
  const focusOnExpand = useRef(false);
  const setCollapsed = (next) => {
    setCollapsedState(next);
    writeNotesCollapsed(kind, ownerId, next);
  };
  const bodyId = `notes-body-${kind}-${ownerId}`;

  const dirty = text !== saved;
  const effectiveBase = dirty ? base : rev;

  // The saved notes changed underneath us (a refresh after something else): follow them, unless there are edits
  useEffect(() => {
    if (text === synced.current && saved !== synced.current) {
      setText(saved);
      setBase(rev);
    }
    synced.current = saved;
  }, [saved, rev]);

  // Keep what's typed as a draft, so leaving the page or a reload doesn't lose it
  useEffect(() => {
    writeDraft(kind, ownerId, dirty ? { text, base: effectiveBase } : null);
  }, [text, base, saved, rev]);

  // The browser asks before closing or reloading with unsaved notes
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (e) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // The box grows with what's typed (up to a point, then scrolls)
  useLayoutEffect(() => {
    const el = areaRef.current;
    if (!el) return; // folded away
    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight + 2, 120), 440)}px`;
    if (focusOnExpand.current) {
      focusOnExpand.current = false;
      el.focus();
    }
  }, [text, collapsed]);

  const save = async (overrideBase) => {
    setPhase("saving");
    setError(null);
    try {
      const out = await onSave({ notes: text, baseRevision: overrideBase ?? effectiveBase });
      synced.current = out.notes; // what the server kept (it tidies the ends), so this isn't seen as an edit
      setText(out.notes);
      setBase(out.notes_revision);
      setConflict(null);
      setRestored(false);
      writeDraft(kind, ownerId, null);
      await refresh();
      setPhase("idle");
    } catch (e) {
      if (e.status === 409 && e.body?.current) {
        setConflict({ notes: e.body.current.notes, revision: e.body.current.notes_revision, updatedAt: e.body.current.notes_updated_at });
        setPhase("idle");
      } else {
        setError(e.message || String(e));
        setPhase("error");
      }
    }
  };
  const discard = () => {
    setText(saved);
    setBase(rev);
    setConflict(null);
    setRestored(false);
    setError(null);
    writeDraft(kind, ownerId, null);
  };
  const useTheirs = async () => {
    // Bring the page's copy of the saved notes up to date FIRST, then swap the text: doing it the other way round
    // would show "Unsaved changes" for a moment, because their text would briefly differ from what the page holds.
    const theirs = conflict;
    setPhase("saving");
    await refresh();
    synced.current = theirs.notes;
    setText(theirs.notes);
    setBase(theirs.revision);
    setConflict(null);
    setRestored(false);
    setPhase("idle");
    writeDraft(kind, ownerId, null);
  };

  const when = (iso) => (iso ? new Date(iso).toLocaleString() : "");
  const busy = phase === "saving";
  let status;
  if (busy) status = { tone: "faint", text: "Saving…" };
  else if (phase === "error") status = { tone: "warn", text: `Couldn't save: ${error}` };
  else if (conflict) status = { tone: "warn", text: "Not saved: someone else saved these notes while you were editing." };
  else if (dirty) {
    status = {
      tone: "warn",
      text: `${restored ? "Restored your unsaved draft. " : ""}Unsaved changes. A draft is kept in this browser until you save.`,
    };
  } else if (rev > 0 && saved) status = { tone: "good", text: `Saved. Last edited ${when(updatedAt)}.` };
  else if (rev > 0) status = { tone: "faint", text: `Notes cleared ${when(updatedAt)}.` };
  else status = { tone: "faint", text: "" }; // never had notes: nothing to say

  // Folded with nothing written (and nothing to warn about), the section is just its heading and the Expand button
  const showBody = !collapsed || !!text || busy || status.tone === "warn";

  const button = { ...ui, fontSize: fs(13), borderRadius: 4, padding: "7px 14px" };
  return (
    <div data-testid="notes-section" data-notes-kind={kind} data-dirty={dirty ? "true" : "false"}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: showBody ? 10 : 0, flexWrap: "wrap" }}>
        <div style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>Notes</div>
        {!collapsed && (
          <span style={{ ...ui, fontSize: fs(12), color: c.textFaint }}>
            {description}
          </span>
        )}
        <button
          data-testid="notes-toggle"
          aria-expanded={!collapsed}
          aria-controls={bodyId}
          onClick={() => setCollapsed(!collapsed)}
          style={{
            display: "flex", alignItems: "center", gap: 6, marginLeft: "auto", ...ui, fontSize: fs(12),
            background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 4, padding: "5px 10px", cursor: "pointer",
          }}
        >
          <ChevronRight size={12} style={{ transform: collapsed ? "none" : "rotate(90deg)", transition: "transform 0.12s ease" }} />
          {collapsed ? "Expand" : "Collapse"}
        </button>
      </div>
      {showBody && (
      <div id={bodyId} style={{ border: `1px solid ${dirty ? c.amber : c.border}`, borderRadius: 4, background: c.panel, padding: 14 }}>
        {collapsed ? (
          <div data-testid="notes-collapsed">
            {text && (
            <div
              data-testid="notes-preview"
              role="button"
              tabIndex={0}
              aria-label="Notes, first line shown. Click to expand and edit."
              title="Click to expand and edit"
              onClick={() => {
                focusOnExpand.current = true;
                setCollapsed(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  focusOnExpand.current = true;
                  setCollapsed(false);
                }
              }}
              style={{
                ...ui, fontSize: fs(14), lineHeight: 1.6, cursor: "pointer", color: text ? c.textPrimary : c.textFaint,
                whiteSpace: "pre-wrap", overflowWrap: "anywhere",
                display: "-webkit-box", WebkitLineClamp: 1, WebkitBoxOrient: "vertical", overflow: "hidden", // the first line, then "…"
              }}
            >
              {text}
            </div>
            )}
            {(busy || status.tone === "warn") && (
              <div data-testid="notes-collapsed-status" style={{ ...ui, fontSize: fs(12), lineHeight: 1.5, marginTop: text ? 8 : 0, color: status.tone === "warn" ? c.amber : c.textFaint }}>
                {status.text}
                {status.tone === "warn" && !busy ? " Expand to review." : ""}
              </div>
            )}
          </div>
        ) : (
          <>
        <textarea
          ref={areaRef}
          data-testid="notes-input"
          aria-label="Notes"
          value={text}
          maxLength={NOTES_MAX}
          placeholder={placeholder}
          onChange={(e) => {
            setText(e.target.value);
            if (phase === "error") setPhase("idle");
          }}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
              e.preventDefault();
              if (dirty && !busy) save();
            }
          }}
          style={{
            display: "block", width: "100%", boxSizing: "border-box", resize: "vertical", minHeight: 120, maxHeight: 440,
            background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary,
            padding: "10px 12px", fontSize: fs(14), lineHeight: 1.6, ...ui,
          }}
        />

        {conflict && (
          <div data-testid="notes-conflict" style={{ marginTop: 12, border: `1px solid ${c.amber}`, borderRadius: 4, padding: 12, background: c.panelAlt }}>
            <div style={{ ...ui, fontSize: fs(13), color: c.heading, marginBottom: 4 }}>Someone else saved these notes while you were editing.</div>
            <div style={{ ...ui, fontSize: fs(12), color: c.textMuted, lineHeight: 1.6, marginBottom: 8 }}>
              Nothing was overwritten. Their version{conflict.updatedAt ? ` (saved ${when(conflict.updatedAt)})` : ""} is below, and yours is still in the box above.
            </div>
            <pre
              data-testid="notes-theirs"
              style={{ ...ui, fontSize: fs(13), color: c.textPrimary, background: c.panel, border: `1px solid ${c.border}`, borderRadius: 3, padding: "8px 10px", margin: "0 0 10px", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 180, overflow: "auto" }}
            >
              {conflict.notes || "(they cleared the notes)"}
            </pre>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button data-testid="notes-use-theirs" onClick={useTheirs} style={{ ...button, background: "none", color: c.textPrimary, border: `1px solid ${c.borderStrong}`, cursor: "pointer" }}>
                Use their version (discard mine)
              </button>
              <button data-testid="notes-overwrite" onClick={() => save(conflict.revision)} disabled={busy} style={{ ...button, background: "none", color: c.amber, border: `1px solid ${c.amber}`, cursor: "pointer" }}>
                Keep mine and overwrite theirs
              </button>
            </div>
          </div>
        )}

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 12, flexWrap: "wrap" }}>
          <div
            data-testid="notes-status"
            style={{ ...ui, fontSize: fs(12), lineHeight: 1.5, flex: 1, minWidth: 200, color: status.tone === "warn" ? c.amber : status.tone === "good" ? c.green : c.textFaint }}
          >
            {status.text}
            {text.length >= NOTES_MAX - 2000 && (
              <span data-testid="notes-count" style={{ ...mono, marginLeft: 10, color: text.length >= NOTES_MAX ? c.danger : c.amber }}>
                {text.length.toLocaleString()} / {NOTES_MAX.toLocaleString()}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              data-testid="notes-discard"
              onClick={discard}
              disabled={!dirty || busy}
              style={{ ...button, background: "none", border: `1px solid ${c.border}`, color: dirty ? c.textPrimary : c.textFaint, cursor: dirty && !busy ? "pointer" : "default", opacity: dirty ? 1 : 0.55 }}
            >
              Discard changes
            </button>
            <button
              data-testid="notes-save"
              onClick={() => save()}
              disabled={!dirty || busy}
              title="Ctrl/⌘ + S"
              style={{ ...button, fontWeight: 600, background: dirty && !busy ? c.amber : c.panelAlt, border: `1px solid ${dirty && !busy ? c.amber : c.border}`, color: dirty && !busy ? c.onAccent : c.textFaint, cursor: dirty && !busy ? "pointer" : "default", padding: "7px 18px" }}
            >
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
          </>
        )}
      </div>
      )}
    </div>
  );
}

function ModelNotes({ model }) {
  return (
    <NotesSection
      kind="model"
      ownerId={model.id}
      saved={model.notes}
      rev={model.notesRevision}
      updatedAt={model.notesUpdatedAt}
      onSave={({ notes, baseRevision }) => saveModelNotes({ modelId: model.id, notes, baseRevision })}
      description="About this model as a whole — print settings that work, where it came from, licence, things to remember."
      placeholder="Nothing written yet. Notes you add here are kept with this model and can be searched from the Models page."
    />
  );
}

function PrinterNotes({ printer }) {
  return (
    <NotesSection
      kind="printer"
      ownerId={printer.id}
      saved={printer.notes}
      rev={printer.notesRevision}
      updatedAt={printer.notesUpdatedAt}
      onSave={({ notes, baseRevision }) => savePrinterNotes({ printerId: printer.id, notes, baseRevision })}
      description="About this printer — nozzle and bed, calibration, maintenance, quirks, where it lives."
      placeholder="Nothing written yet. Notes you add here are kept with this printer."
    />
  );
}

// ---- searching the Models list ----
// A search is split into words and EVERY word must be found ("great white" finds GreatWhiteShark; "frog shark"
// finds nothing). A word matches the model's own name first; failing that, the names of its 3MF files, the
// printers it's sliced for, or the slicer used. That makes "VT 1190" or "prusa" useful searches, and the row says
// which of those a model matched through, so a result is never a mystery.
const searchWords = (query) => query.trim().toLowerCase().split(/\s+/).filter(Boolean);

// -> null if the model doesn't match every word; otherwise { reasons: [...] } (empty when its own name matched)
function matchModel(model, words, others) {
  if (words.length === 0) return { reasons: [] };
  const name = model.name.toLowerCase();
  const reasons = [];
  for (const word of words) {
    if (name.includes(word)) continue;
    const hit = others.find((o) => o.text.toLowerCase().includes(word));
    if (!hit) return null;
    const reason = hit.kind === "note" ? `note “${excerptAround(hit.text, word)}”` : `${hit.kind} ${hit.text}`;
    if (!reasons.includes(reason)) reasons.push(reason);
  }
  return { reasons };
}

// A short stretch of a long text around where a word was found, for saying why something matched
function excerptAround(text, word) {
  const i = text.toLowerCase().indexOf(word);
  const start = Math.max(0, i - 24);
  const end = Math.min(text.length, i + word.length + 40);
  return (start > 0 ? "…" : "") + text.slice(start, end).replace(/\s+/g, " ").trim() + (end < text.length ? "…" : "");
}

// Everything besides its own name that a model can be found by
function searchableExtras(model, bundles, printers) {
  const out = [];
  (model.versions || []).forEach((v) => v.filename && out.push({ kind: "file", text: v.filename }));
  bundles.forEach((b) => {
    const printer = printers.find((p) => p.id === b.printerId);
    if (printer) out.push({ kind: "printer", text: printer.name });
    (b.versions || []).forEach((v) => v.filename && out.push({ kind: "3MF", text: v.filename }));
    if (b.slicer) out.push({ kind: "slicer", text: b.slicer });
  });
  if (model.notes) out.push({ kind: "note", text: model.notes }); // last: a note only explains a match nothing else does
  return out;
}

// The text with the searched words picked out
function Highlighted({ text, words }) {
  if (!words || words.length === 0) return text;
  const escaped = [...words].sort((a, b) => b.length - a.length).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const parts = text.split(new RegExp(`(${escaped.join("|")})`, "gi"));
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} data-testid="search-hit" style={{ background: c.amberDim, color: c.amber, borderRadius: 2, padding: "0 1px" }}>
        {part}
      </mark>
    ) : (
      part
    )
  );
}

function ModelListRow({ model, bundleCount, printerCount, borderBottom, borderRight, onOpen, words = [], reasons = [] }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      data-testid="model-row"
      onClick={onOpen}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        minWidth: 0,
        padding: "10px 14px",
        cursor: "pointer",
        background: hover ? c.panelAlt : "transparent",
        borderBottom: borderBottom ? `1px solid ${c.border}` : "none",
        borderRight: borderRight ? `1px solid ${c.border}` : "none",
      }}
    >
      <Thumb src={model.thumb} size={56} background="#FFFFFF" placeholderIcon />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          data-testid="model-name"
          title={model.name}
          style={{ ...ui, fontSize: fs(14), color: c.heading, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          <Highlighted text={model.name} words={words} />
        </div>
        <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, marginTop: 3 }}>Added {model.added}</div>
        {reasons.length > 0 && (
          <div
            data-testid="search-reason"
            title={reasons.join("\n")}
            style={{ ...ui, fontSize: fs(11), color: c.teal, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          >
            Matched: {reasons.slice(0, 2).join(", ")}
            {reasons.length > 2 ? "…" : ""}
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 6, flexShrink: 0, alignItems: "center" }}>
        {model.notes && (
          <span data-testid="has-notes" title={`Has notes: ${model.notes.slice(0, 120)}${model.notes.length > 120 ? "…" : ""}`} style={{ display: "flex" }}>
            <StickyNote size={14} color={c.textFaint} />
          </span>
        )}
        <Badge>{model.type}</Badge>
        <Badge tone="teal">{bundleCount} 3MF</Badge>
        <Badge tone="teal">{printerCount} {printerCount === 1 ? "Printer" : "Printers"}</Badge>
      </div>
    </div>
  );
}

// Previews drawn by older versions of Farmhand (the first one thinned detailed models, leaving them
// see-through) are redrawn from their files, one at a time so progress shows.
function RedrawPreviewsDialog({ onClose }) {
  const { sourceModels, refresh } = useData();
  const targets = sourceModels.filter((m) => m.type === "STL" && m.versions.length > 0);
  const [phase, setPhase] = useState("confirm"); // confirm | running | done
  const [done, setDone] = useState(0);
  const [result, setResult] = useState(null);

  const run = async () => {
    setPhase("running");
    setDone(0);
    let redrawn = 0;
    let skipped = 0;
    const failed = [];
    for (let i = 0; i < targets.length; i += 1) {
      const m = targets[i];
      try {
        const r = await redrawPreview({ modelId: m.id, version: m.versions[0].v }); // the newest version is what the list shows
        if (r.updated) redrawn += 1;
        else skipped += 1;
      } catch (e) {
        failed.push({ name: m.name, error: e.message || String(e) });
      }
      setDone(i + 1);
    }
    bustThumbnails(); // same URLs, new pictures: make the browser fetch them again
    await refresh().catch(() => {});
    setResult({ redrawn, skipped, failed });
    setPhase("done");
  };

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const button = (label, onClick, primary, extra = {}) => (
    <button
      onClick={onClick}
      style={{ ...ui, fontSize: fs(13), background: primary ? c.amber : "none", color: primary ? c.onAccent : c.textMuted, border: primary ? "none" : `1px solid ${c.border}`, borderRadius: 3, padding: "7px 14px", fontWeight: primary ? 600 : 400, cursor: "pointer", ...extra }}
    >
      {label}
    </button>
  );

  if (phase === "running") {
    return (
      <div data-testid="redraw-progress">
        <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, marginBottom: 10 }}>
          Redrawing {Math.min(done + 1, targets.length)} of {targets.length}…
        </div>
        <div style={{ height: 6, borderRadius: 3, background: c.panelAlt, overflow: "hidden" }}>
          <div style={{ width: `${targets.length ? (done / targets.length) * 100 : 0}%`, height: "100%", background: c.amber, transition: "width 0.2s ease" }} />
        </div>
      </div>
    );
  }
  if (phase === "done") {
    return (
      <div data-testid="redraw-summary">
        <div style={{ ...ui, fontSize: fs(14), color: c.heading, marginBottom: 8 }}>
          Redrew {plural(result.redrawn, "preview", "previews")}.
        </div>
        {result.skipped > 0 && (
          <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, lineHeight: 1.6, marginBottom: 8 }}>
            {plural(result.skipped, "file couldn't be drawn", "files couldn't be drawn")} (not a readable STL) and were left as they were.
          </div>
        )}
        {result.failed.length > 0 && (
          <div style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.6, marginBottom: 8 }}>
            {plural(result.failed.length, "preview couldn't be redrawn", "previews couldn't be redrawn")}:
            {result.failed.map((f) => (
              <div key={f.name}>
                <span style={mono}>{f.name}</span> — {f.error}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>{button("Done", onClose, false)}</div>
      </div>
    );
  }
  return (
    <>
      <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6, marginBottom: 14 }}>
        Redraw the previews of <b style={{ color: c.heading }}>{plural(targets.length, "STL model", "STL models")}</b> from their files.
        Use this after an update that improves how previews are drawn — earlier ones of detailed models can look thin or
        see-through. Your files aren't changed, and a preview that can't be redrawn is left as it was.
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        {button("Cancel", onClose, false)}
        <span data-testid="redraw-start">
          {button(`Redraw ${plural(targets.length, "preview", "previews")}`, run, true, {
            opacity: targets.length === 0 ? 0.5 : 1,
            pointerEvents: targets.length === 0 ? "none" : "auto",
          })}
        </span>
      </div>
    </>
  );
}

const SCAN_BATCH = 10; // files added per request, so a big import shows progress and one slow batch can't time out the lot

function ScanStlDialog({ onClose }) {
  const { refresh } = useData();
  const [phase, setPhase] = useState("scanning"); // scanning | results | adding | done | error
  const [scan, setScan] = useState(null);
  const [selected, setSelected] = useState({}); // path -> chosen?
  const [progress, setProgress] = useState(0);
  const [summary, setSummary] = useState(null); // { added, failed: [{name, error}], stopped }
  const [error, setError] = useState(null);

  useEffect(() => {
    scanStlFolder()
      .then((result) => {
        setScan(result);
        setSelected(Object.fromEntries(result.files.map((f) => [f.path, true]))); // everything found, ticked
        setPhase("results");
      })
      .catch((e) => {
        setError(e.message || String(e));
        setPhase("error");
      });
  }, []);

  const files = scan?.files || [];
  const chosen = files.filter((f) => selected[f.path]);
  const allChosen = files.length > 0 && chosen.length === files.length;

  const addChosen = async () => {
    const byPath = Object.fromEntries(files.map((f) => [f.path, f]));
    setProgress(0);
    setPhase("adding");
    let added = 0;
    const failed = [];
    let stopped = null;
    try {
      for (let i = 0; i < chosen.length; i += SCAN_BATCH) {
        const batch = chosen.slice(i, i + SCAN_BATCH);
        const { results } = await importScannedFiles(batch.map((f) => f.path));
        for (const r of results) {
          if (r.ok) added += 1;
          else failed.push({ name: byPath[r.path]?.name || r.path, error: r.error });
        }
        setProgress(Math.min(i + SCAN_BATCH, chosen.length));
      }
    } catch (e) {
      stopped = e.message || String(e); // e.g. the share went away part-way; what was added is kept
    }
    await refresh().catch(() => {});
    setSummary({ added, failed, stopped });
    setPhase("done");
  };

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const closeBtn = (label = "Close") => (
    <button
      onClick={onClose}
      style={{ ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "7px 14px", cursor: "pointer" }}
    >
      {label}
    </button>
  );

  if (phase === "scanning") {
    return <div style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>Looking through the STL folder…</div>;
  }
  if (phase === "error") {
    return (
      <>
        <div style={{ ...ui, fontSize: fs(13), color: c.amber, lineHeight: 1.6, marginBottom: 14 }}>{error}</div>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>{closeBtn()}</div>
      </>
    );
  }
  if (phase === "adding") {
    const pct = chosen.length ? Math.round((progress / chosen.length) * 100) : 0;
    return (
      <div data-testid="scan-progress">
        <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, marginBottom: 10 }}>
          Moving {Math.min(progress + 1, chosen.length)}–{Math.min(progress + SCAN_BATCH, chosen.length)} of {chosen.length}… (making previews can take a moment)
        </div>
        <div style={{ height: 6, borderRadius: 3, background: c.panelAlt, overflow: "hidden" }}>
          <div style={{ width: `${pct}%`, height: "100%", background: c.amber, transition: "width 0.2s ease" }} />
        </div>
      </div>
    );
  }
  if (phase === "done") {
    return (
      <div data-testid="scan-summary">
        <div style={{ ...ui, fontSize: fs(14), color: c.heading, marginBottom: 8 }}>
          Moved {plural(summary.added, "file", "files")} into the library.
        </div>
        {summary.added > 0 && (
          <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, lineHeight: 1.6, marginBottom: 8 }}>
            They're now filed in Farmhand's own folders. The folders they came from were left as they were.
          </div>
        )}
        {summary.stopped && (
          <div style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.6, marginBottom: 8 }}>
            It stopped early: {summary.stopped} What was moved so far is kept — scan again to continue.
          </div>
        )}
        {summary.failed.length > 0 && (
          <div style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.6, marginBottom: 8 }}>
            {plural(summary.failed.length, "file couldn't be added (it stays where it was)", "files couldn't be added (they stay where they were)")}:
            {summary.failed.map((f) => (
              <div key={f.name}>
                <span style={mono}>{f.name}</span> — {f.error}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>{closeBtn("Done")}</div>
      </div>
    );
  }

  // results
  if (files.length === 0) {
    return (
      <>
        <div data-testid="scan-none" style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6, marginBottom: 14 }}>
          No new files found in <span style={mono}>{scan.root}</span>. Everything there is already in the library.
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>{closeBtn()}</div>
      </>
    );
  }
  return (
    <div data-testid="scan-results">
      <div style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6, marginBottom: 10 }}>
        Found <b style={{ color: c.heading }}>{plural(files.length, "new file", "new files")}</b>
        {scan.truncated ? " (that's the first batch — add these, then scan again for more)" : ""} in{" "}
        <span style={mono}>{scan.root}</span>.
      </div>
      <div data-testid="scan-move-note" style={{ ...ui, fontSize: fs(12), color: c.textFaint, lineHeight: 1.6, marginBottom: 12 }}>
        Adding a file <b style={{ color: c.textMuted }}>moves</b> it into Farmhand's own folders, filed the same way an upload is (
        <span style={mono}>{scan.root}/&lt;number&gt;/v1/</span>), so it won't be where it is now. The folders it's in are left as they
        are, and its note remembers where it came from.
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 6, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={allChosen}
          onChange={(e) => setSelected(Object.fromEntries(files.map((f) => [f.path, e.target.checked])))}
          style={{ accentColor: c.amber }}
        />
        Select all
      </label>
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, maxHeight: 320, overflow: "auto", marginBottom: 14 }}>
        {files.map((f, i) => (
          <label
            key={f.path}
            data-testid="scan-row"
            style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", borderTop: i === 0 ? "none" : `1px solid ${c.border}`, cursor: "pointer" }}
          >
            <input
              type="checkbox"
              checked={!!selected[f.path]}
              onChange={(e) => setSelected((prev) => ({ ...prev, [f.path]: e.target.checked }))}
              style={{ accentColor: c.amber, flexShrink: 0 }}
            />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ ...ui, fontSize: fs(13), color: c.heading, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</div>
              <div style={{ ...mono, fontSize: fs(11), color: c.textFaint, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {f.folder || "top level"}
              </div>
            </div>
            {f.nameInLibrary && <Badge tone="amber">name already in library</Badge>}
            <Badge>{f.fileType}</Badge>
            <span style={{ ...mono, fontSize: fs(11), color: c.textFaint, width: 58, textAlign: "right", flexShrink: 0 }}>{formatBytes(f.sizeBytes)}</span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        {closeBtn("Cancel")}
        <button
          data-testid="scan-add"
          onClick={addChosen}
          disabled={chosen.length === 0}
          style={{ ...ui, fontSize: fs(13), background: c.amber, color: c.onAccent, border: "none", borderRadius: 3, padding: "7px 14px", fontWeight: 600, cursor: chosen.length === 0 ? "default" : "pointer", opacity: chosen.length === 0 ? 0.5 : 1 }}
        >
          Move {chosen.length} into the library
        </button>
      </div>
    </div>
  );
}

function UploadBar({ onUploadStl, onUploadBundle, onScan, bundleLabel = "Upload 3MF" }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {onScan && (
        <button
          onClick={onScan}
          title="Look through the STL folder for files that were added from outside Farmhand"
          style={{ display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 4, padding: "7px 12px", cursor: "pointer" }}
        >
          <Search size={13} />
          Scan STL folder
        </button>
      )}
      <button
        onClick={onUploadStl}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          ...ui,
          fontSize: fs(13),
          background: "none",
          color: c.textMuted,
          border: `1px solid ${c.border}`,
          borderRadius: 4,
          padding: "7px 12px",
          cursor: "pointer",
        }}
      >
        <Upload size={13} />
        Upload STL
      </button>
      <button
        onClick={onUploadBundle}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          ...ui,
          fontSize: fs(13),
          background: "none",
          color: c.textMuted,
          border: `1px solid ${c.border}`,
          borderRadius: 4,
          padding: "7px 12px",
          cursor: "pointer",
        }}
      >
        <Upload size={13} />
        {bundleLabel}
      </button>
    </div>
  );
}

function ModelsSection({ path, setPath, compareSelection, toggleCompareSelect, sort, onSortChange }) {
  const { sourceModels, printers, bundlesForModel, versionsByBundle, sourceVersionsByModel } = useData();
  const view = path[1];
  const expansion = useBundleExpansion();
  const [sourceOverride, setSourceOverride] = useState(null); // null = the default for its length
  const [uploadModal, setUploadModal] = useState(null); // null | "stl" | "3mf" | "scan" | "redraw"
  const [addFileOpen, setAddFileOpen] = useState(false);
  const [newVersionOpen, setNewVersionOpen] = useState(false);
  const narrow = useMediaQuery("(max-width: 760px)"); // two columns, or one on a narrow screen
  const [query, setQuery] = useState(""); // the search; kept while you open a model and come back
  const searchRef = useRef(null);

  // "/" jumps to the search box (unless you're already typing somewhere)
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || view || uploadModal) return;
      const tag = e.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target?.isContentEditable) return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, uploadModal]);

  useEffect(() => {
    setSourceOverride(null);
  }, [view?.modelId]);

  if (!view) {
    const rows = sourceModels.map((m) => {
      const mBundles = bundlesForModel(m.id);
      return { m, bundleCount: mBundles.length, printerCount: new Set(mBundles.map((bundle) => bundle.printerId)).size };
    });
    const words = searchWords(query);
    const matched = [];
    rows.forEach((row) => {
      const hit = matchModel(row.m, words, words.length ? searchableExtras(row.m, bundlesForModel(row.m.id), printers) : []);
      if (hit) matched.push({ ...row, reasons: hit.reasons });
    });
    const sorted = sortModelRows(matched, sort);
    const searching = words.length > 0;
    const columns = narrow ? 1 : 2;
    const lastRow = Math.floor((sorted.length - 1) / columns);
    const chooseSort = onSortChange; // kept with the other settings, so every browser shows the same order
    const control = { background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, fontSize: fs(13), ...ui };

    return (
      <div>
        <div style={{ position: "relative", maxWidth: 460, marginBottom: 12 }}>
          <Search size={15} color={c.textFaint} style={{ position: "absolute", left: 11, top: 10, pointerEvents: "none" }} />
          <input
            ref={searchRef}
            data-testid="model-search"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                if (query) setQuery("");
                else e.currentTarget.blur();
              }
            }}
            placeholder="Search models, 3MF files, printers or notes…   ( / )"
            aria-label="Search models"
            autoComplete="off"
            spellCheck={false}
            style={{ ...control, width: "100%", boxSizing: "border-box", padding: "8px 34px 8px 34px" }}
          />
          {query && (
            <button
              data-testid="model-search-clear"
              onClick={() => {
                setQuery("");
                searchRef.current?.focus();
              }}
              aria-label="Clear search"
              title="Clear search (Esc)"
              style={{ position: "absolute", right: 6, top: 6, width: 24, height: 24, display: "flex", alignItems: "center", justifyContent: "center", background: "none", border: "none", color: c.textMuted, cursor: "pointer", padding: 0 }}
            >
              <X size={14} />
            </button>
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ ...ui, fontSize: fs(12), color: c.textFaint }}>Sort by</span>
            <select
              data-testid="model-sort"
              value={sort.key}
              onChange={(e) => {
                const option = MODEL_SORTS.find((o) => o.key === e.target.value);
                chooseSort({ key: option.key, dir: option.dir });
              }}
              style={{ ...control, padding: "6px 8px" }}
            >
              {MODEL_SORTS.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </select>
            <button
              data-testid="model-sort-dir"
              onClick={() => chooseSort({ ...sort, dir: sort.dir === "asc" ? "desc" : "asc" })}
              title={sort.dir === "asc" ? "Ascending — click to reverse" : "Descending — click to reverse"}
              aria-label={sort.dir === "asc" ? "Ascending, click to reverse" : "Descending, click to reverse"}
              style={{ ...control, display: "flex", alignItems: "center", justifyContent: "center", width: 30, height: 30, cursor: "pointer", padding: 0 }}
            >
              {sort.dir === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
            </button>
            <span data-testid="model-count" style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginLeft: 6 }}>
              {searching ? `${sorted.length} of ${rows.length}` : sorted.length} {(searching ? rows.length : sorted.length) === 1 ? "model" : "models"}
            </span>
            <button
              onClick={() => setUploadModal("redraw")}
              title="Redraw the previews from their files with the current renderer"
              style={{ ...ui, fontSize: fs(12), background: "none", color: c.textFaint, border: "none", textDecoration: "underline", cursor: "pointer", marginLeft: 6 }}
            >
              Redraw previews
            </button>
          </div>
          <UploadBar
            onUploadStl={() => setUploadModal("stl")}
            onUploadBundle={() => setUploadModal("3mf")}
            onScan={() => setUploadModal("scan")}
          />
        </div>

        {sorted.length === 0 && searching ? (
          <div data-testid="model-search-empty" style={{ ...ui, fontSize: fs(13), color: c.textMuted, padding: "24px 4px", lineHeight: 1.7 }}>
            No models match <b style={{ color: c.heading }}>“{query.trim()}”</b>. Every word has to match the name, a 3MF file, a printer, the slicer or the notes.{" "}
            <button
              data-testid="model-search-empty-clear"
              onClick={() => setQuery("")}
              style={{ ...ui, fontSize: fs(13), background: "none", border: "none", color: c.amber, textDecoration: "underline", cursor: "pointer", padding: 0 }}
            >
              Clear search
            </button>
          </div>
        ) : sorted.length === 0 ? (
          <div style={{ ...ui, fontSize: fs(13), color: c.textFaint, padding: "24px 4px" }}>
            No models yet — upload an STL, or scan the STL folder for files already there.
          </div>
        ) : (
          <div
            data-testid="model-list"
            style={{
              display: "grid",
              gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
              border: `1px solid ${c.border}`,
              borderRadius: 4,
              background: c.panel,
              overflow: "hidden",
            }}
          >
            {sorted.map(({ m, bundleCount, printerCount, reasons }, i) => (
              <ModelListRow
                key={m.id}
                model={m}
                words={words}
                reasons={reasons}
                bundleCount={bundleCount}
                printerCount={printerCount}
                borderBottom={Math.floor(i / columns) < lastRow}
                borderRight={columns === 2 && i % 2 === 0}
                onOpen={() => setPath([{ label: "Models" }, { modelId: m.id }])}
              />
            ))}
          </div>
        )}

        {uploadModal === "stl" && (
          <Modal title="Upload STL / OBJ / STEP" onClose={() => setUploadModal(null)}>
            <UploadStlForm onClose={() => setUploadModal(null)} />
          </Modal>
        )}
        {uploadModal === "3mf" && (
          <Modal title="Upload 3MF" onClose={() => setUploadModal(null)}>
            <Upload3mfForm onClose={() => setUploadModal(null)} />
          </Modal>
        )}
        {uploadModal === "scan" && (
          <Modal title="Scan STL folder" onClose={() => setUploadModal(null)} width={680}>
            <ScanStlDialog onClose={() => setUploadModal(null)} />
          </Modal>
        )}
        {uploadModal === "redraw" && (
          <Modal title="Redraw previews" onClose={() => setUploadModal(null)}>
            <RedrawPreviewsDialog onClose={() => setUploadModal(null)} />
          </Modal>
        )}
      </div>
    );
  }

  const model = sourceModels.find((m) => m.id === view.modelId);
  const sourceList = sourceVersionsByModel[model.id] || [];
  const hasFile = sourceList.length > 0; // a folder can exist with no file yet
  const sourceLatest = sourceList[0];
  const sourceRest = sourceList.slice(1);
  const sourceExpanded = sourceOverride ?? false; // older versions start hidden
  // Grouped by printer, and under each printer the most recently updated entry first
  const modelBundles = [...bundlesForModel(model.id)].sort((a, b) => {
    const pa = printers.find((p) => p.id === a.printerId)?.name || "";
    const pb = printers.find((p) => p.id === b.printerId)?.name || "";
    return nameCollator.compare(pa, pb) || newestFirst(a, b);
  });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
      <div>
        {addFileOpen && (
          <Modal title="Add model file" onClose={() => setAddFileOpen(false)}>
            <AddModelFileForm model={model} onClose={() => setAddFileOpen(false)} />
          </Modal>
        )}
        {newVersionOpen && (
          <Modal title="Upload a new version" onClose={() => setNewVersionOpen(false)}>
            <AddModelFileForm model={model} isNewVersion onClose={() => setNewVersionOpen(false)} />
          </Modal>
        )}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <SectionLabel>Model file</SectionLabel>
          <div style={{ display: "flex", gap: 8 }}>
            {hasFile && (
              <button
                data-testid="stl-new-version"
                onClick={() => setNewVersionOpen(true)}
                title="Upload a newer version of this model file"
                style={{ display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 4, padding: "5px 10px", cursor: "pointer", marginBottom: 10 }}
              >
                <Upload size={12} />
                New version
              </button>
            )}
            <DeleteModelButton model={model} onDeleted={() => setPath([{ label: "Models" }])} />
          </div>
        </div>
        <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
          <div
            onClick={() => sourceRest.length > 0 && setSourceOverride(!sourceExpanded)}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 16px",
              background: c.panelAlt,
              cursor: sourceRest.length > 0 ? "pointer" : "default",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Thumb src={model.thumb} size={64} background="#FFFFFF" placeholderIcon />
              <div>
                <div style={{ ...ui, fontSize: fs(14), color: c.heading }}>
                  <EditableName value={model.name} label="this model file" extension={{ STL: ".stl", OBJ: ".obj", STEP: ".step" }[model.type] || ".stl"} testId="model-name" textStyle={{ ...ui, fontSize: fs(14) }} onSave={(name) => renameModel(model.id, name)} />
                </div>
                <div style={{ marginTop: 5 }}>
                  <Badge>{model.type}</Badge>
                </div>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ ...ui, fontSize: fs(12), color: c.textFaint }}>
                {sourceList.length} version{sourceList.length === 1 ? "" : "s"}
              </span>
              {sourceRest.length > 0 && (
                <ChevronRight
                  size={15}
                  color={c.textFaint}
                  style={{
                    transform: sourceExpanded ? "rotate(90deg)" : "rotate(0deg)",
                    transition: "transform 0.12s ease",
                  }}
                />
              )}
            </div>
          </div>
          {hasFile ? (
            <>
              <VersionRow ver={sourceLatest} isLatest model={model} />
              {sourceExpanded && sourceRest.map((v) => <VersionRow key={v.v} ver={v} model={model} />)}
            </>
          ) : (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px" }}>
              <span style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>No model file uploaded yet.</span>
              <button
                onClick={() => setAddFileOpen(true)}
                style={{ display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 4, padding: "5px 10px", cursor: "pointer" }}
              >
                <Upload size={12} />
                Add file
              </button>
            </div>
          )}
        </div>
      </div>

      <ModelNotes key={model.id} model={model} />

      <div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <SectionLabel>3MF files by printer</SectionLabel>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <VersionsToggleAll bundleList={modelBundles} expansion={expansion} />
            <button
              onClick={() => setUploadModal("3mf")}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                ...ui,
                fontSize: fs(12),
                background: "none",
                color: c.textMuted,
                border: `1px solid ${c.border}`,
                borderRadius: 4,
                padding: "5px 10px",
                cursor: "pointer",
                marginBottom: 10,
              }}
            >
              <Upload size={12} />
              Upload 3MF
            </button>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {modelBundles.map((b) => {
            const printer = printers.find((p) => p.id === b.printerId);
            const vlist = versionsByBundle[b.id] || [];
            const latest = vlist[0];
            const rest = vlist.slice(1);
            const isExpanded = expansion.isExpanded(b.id, vlist.length);
            const isSelected = vlist.some((v) => compareSelection.includes(v.id)); // any of its versions picked
            return (
              <div
                key={b.id}
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
                    style={{ display: "flex", flexDirection: "column", gap: 4, cursor: rest.length > 0 ? "pointer" : "default", minWidth: 0, flex: 1 }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Printer size={15} color={c.textFaint} />
                      <span style={{ ...ui, fontSize: fs(14), color: c.heading }}>{printer.name}</span>
                      <Lock size={12} color={c.textFaint} />
                      <Badge>{b.slicer}</Badge>
                    </div>
                    <div style={{ ...mono, fontSize: fs(11), color: c.textFaint, paddingLeft: 23 }}>
                      <EditableName value={b.name} label="this 3MF file" extension=".3mf" boxed testId="bundle-name" textStyle={{ ...mono, fontSize: fs(12) }} onSave={(name) => renameBundleVersion(b.versions[0].id, name)} />
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                    <span style={{ ...ui, fontSize: fs(12), color: c.textFaint }}>
                      {vlist.length} version{vlist.length === 1 ? "" : "s"}
                    </span>
                    {rest.length > 0 && (
                      <VersionsToggle open={isExpanded} olderCount={rest.length} controlsId={`versions-${b.id}`} onToggle={() => expansion.set(b.id, !isExpanded)} />
                    )}
                    <NewVersionButton bundle={b} />
                    <DeleteBundleButton bundle={b} />
                  </div>
                </div>
                <VersionRow ver={latest} isLatest showFileStatus bundle={b} compareSelection={compareSelection} onToggleCompare={toggleCompareSelect} />
                <div id={`versions-${b.id}`}>
                  {isExpanded && rest.map((v) => <VersionRow key={v.v} ver={v} showFileStatus bundle={b} compareSelection={compareSelection} onToggleCompare={toggleCompareSelect} />)}
                </div>
                <BundleNotes key={b.id} bundle={b} />
              </div>
            );
          })}
        </div>
      </div>

      {uploadModal === "3mf" && (
        <Modal title="Upload 3MF" onClose={() => setUploadModal(null)}>
          <Upload3mfForm presetModel={model} onClose={() => setUploadModal(null)} />
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// App shell
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Storage: where the STL files and the 3MF files are kept
// ---------------------------------------------------------------------------
function formatBytes(n) {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

function FolderPicker({ title, startPath, shares = [], onSelect, onClose }) {
  const [listing, setListing] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const connected = shares.filter((sh) => sh.mounted);

  const load = async (path) => {
    setError(null);
    try {
      setListing(await browseStorage(path));
    } catch (e) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => {
    // Open where the current choice is; if that's gone or out of bounds, start from the top
    browseStorage(startPath)
      .then(setListing)
      .catch(() => browseStorage(null).then(setListing).catch((e) => setError(e.message || String(e))));
  }, []);

  const makeFolder = async () => {
    setCreating(true);
    setError(null);
    try {
      setListing(await createFolder({ parent: listing.path, name: newName }));  // step into the new folder
      setNewOpen(false);
      setNewName("");
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setCreating(false);
    }
  };

  const choose = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSelect(listing.path);
      onClose();
    } catch (e) {
      setError(e.message || String(e));
      setBusy(false);
    }
  };

  return (
    <Modal title={title} onClose={busy ? () => {} : onClose} width={580}>
      {!listing && !error && <div style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>Loading folders…</div>}
      {listing && connected.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          <span style={{ ...ui, fontSize: fs(12), color: c.textFaint }}>Connected shares:</span>
          {connected.map((sh) => (
            <button
              key={sh.id}
              onClick={() => load(sh.mountPoint)}
              style={{ display: "flex", alignItems: "center", gap: 5, ...ui, fontSize: fs(12), background: c.tealDim, color: c.teal, border: `1px solid ${c.teal}`, borderRadius: 3, padding: "3px 9px", cursor: "pointer" }}
            >
              <Server size={11} />
              {sh.name}
            </button>
          ))}
        </div>
      )}
      {listing && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <button
              onClick={() => load(listing.parent)}
              disabled={!listing.parent}
              title="Up one folder"
              aria-label="Up one folder"
              style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 28, height: 28, flexShrink: 0, borderRadius: 3, border: `1px solid ${c.border}`, background: "transparent", color: listing.parent ? c.textMuted : c.textFaint, cursor: listing.parent ? "pointer" : "default" }}
            >
              <ArrowUp size={14} />
            </button>
            <div data-testid="picker-path" style={{ ...mono, fontSize: fs(12), color: c.heading, wordBreak: "break-all", flex: 1 }}>{listing.path}</div>
            <button
              onClick={() => setNewOpen((v) => !v)}
              style={{ display: "flex", alignItems: "center", gap: 5, flexShrink: 0, ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "4px 9px", cursor: "pointer" }}
            >
              <FolderPlus size={13} />
              New folder
            </button>
          </div>
          {newOpen && (
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && newName.trim() && !creating && makeFolder()}
                placeholder="Folder name"
                style={{ flex: 1, background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, padding: "7px 10px", fontSize: fs(13), ...ui }}
              />
              <button
                onClick={makeFolder}
                disabled={creating || !newName.trim()}
                style={{ ...ui, fontSize: fs(13), background: c.amberDim, color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 4, padding: "6px 12px", cursor: creating || !newName.trim() ? "default" : "pointer", opacity: creating || !newName.trim() ? 0.6 : 1 }}
              >
                {creating ? "Creating…" : "Create"}
              </button>
            </div>
          )}
          <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, maxHeight: 280, overflow: "auto", marginBottom: 10 }}>
            {listing.entries.length === 0 && (
              <div style={{ ...ui, fontSize: fs(13), color: c.textFaint, padding: "14px 16px" }}>No sub-folders here.</div>
            )}
            {listing.entries.map((e, i) => (
              <button
                key={e.path}
                onClick={() => load(e.path)}
                style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left", padding: "9px 14px", background: "transparent", border: "none", borderTop: i === 0 ? "none" : `1px solid ${c.border}`, color: c.textPrimary, cursor: "pointer", ...ui, fontSize: fs(13) }}
              >
                <Folder size={15} color={c.textFaint} />
                <span style={{ flex: 1 }}>{e.name}</span>
                {e.isMount && <Badge tone="teal">mounted share</Badge>}
              </button>
            ))}
          </div>
          <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, lineHeight: 1.5, marginBottom: 14 }}>
            Only folders on a connected network share (or in Farmhand's own storage) can be chosen. Open a share
            above, then pick a folder on it — or make one with New folder.
          </div>
        </>
      )}
      {error && <div style={{ ...ui, fontSize: fs(12), color: c.amber, marginBottom: 12, lineHeight: 1.5 }}>{error}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button
          onClick={onClose}
          disabled={busy}
          style={{ ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "7px 14px", cursor: "pointer" }}
        >
          Cancel
        </button>
        <button
          onClick={choose}
          disabled={busy || !listing}
          style={{ ...ui, fontSize: fs(13), background: c.amber, color: c.onAccent, border: "none", borderRadius: 3, padding: "7px 14px", fontWeight: 600, cursor: busy || !listing ? "default" : "pointer", opacity: busy || !listing ? 0.7 : 1 }}
        >
          {busy ? "Saving…" : "Use this folder"}
        </button>
      </div>
    </Modal>
  );
}

function LocationCard({ title, blurb, location, onChange, onReset }) {
  const s = location.status;
  const problem = !s.exists
    ? "Folder not found"
    : !s.writable
      ? "Not writable"
      : !s.markerOk
        ? "Marker missing — the share may be unmounted"
        : null;
  return (
    <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div style={{ ...ui, fontSize: fs(15), color: c.heading }}>{title}</div>
        <div style={{ display: "flex", gap: 6 }}>
          <Badge tone={location.isDefault ? "muted" : "teal"}>{location.isDefault ? "default location" : "chosen location"}</Badge>
          {s.ready ? <Badge tone="green">ready</Badge> : <Badge tone="amber">{problem}</Badge>}
        </div>
      </div>
      <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 12 }}>{blurb}</div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", border: `1px solid ${c.border}`, borderRadius: 4, background: c.panelAlt, marginBottom: 10 }}>
        <HardDrive size={15} color={c.textFaint} />
        <span style={{ ...mono, fontSize: fs(12), color: c.heading, wordBreak: "break-all" }}>{location.path}</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        {s.separateVolume ? <Badge tone="teal">separate volume (network or external)</Badge> : <Badge>same disk as the app</Badge>}
        <span style={{ ...ui, fontSize: fs(12), color: c.textFaint }}>
          {formatBytes(s.freeBytes)} free of {formatBytes(s.totalBytes)}
        </span>
      </div>
      {!location.isDefault && !s.separateVolume && (
        <div style={{ ...ui, fontSize: fs(12), color: c.amber, marginBottom: 12, lineHeight: 1.5 }}>
          This folder is on the same disk as Farmhand's own data. If you meant a network share, check that it's mounted.
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={onChange}
          style={{ ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.borderStrong}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" }}
        >
          Change…
        </button>
        {!location.isDefault && (
          <button
            onClick={onReset}
            style={{ ...ui, fontSize: fs(13), background: "none", color: c.textFaint, border: `1px solid ${c.border}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" }}
          >
            Use default
          </button>
        )}
      </div>
    </div>
  );
}

function ShareForm({ existing, capability, onClose, onSaved }) {
  const editing = !!existing;
  const [name, setName] = useState(existing?.name || "");
  const [location, setLocation] = useState(existing?.address || ""); // ONE address: server, share and sub-folder together
  const [username, setUsername] = useState(existing?.username || "");
  const [password, setPassword] = useState("");
  const [domain, setDomain] = useState(existing?.domain || "");
  const [version, setVersion] = useState(existing?.version || "auto");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  // How the address reads: decides SMB-only fields and the version list. Just a preview —
  // the server parses and validates the address itself.
  const parsed = parseLocation(location);
  const described = describeLocation(parsed);
  const protocol = editing ? existing.protocol : parsed.protocol || "smb";
  const smb = protocol === "smb";
  const versions = smb ? ["auto", "3.1.1", "3.0", "2.1"] : ["4", "3"];
  const versionValue = versions.includes(version) ? version : versions[0]; // switching SMB↔NFS while typing resets it

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!name.trim() && !editing) return setErrorMsg("Give the share a name.");
    if (!location.trim()) return setErrorMsg("Enter the NAS folder's address.");
    if (editing && parsed.protocol && parsed.protocol !== existing.protocol) {
      return setErrorMsg(`This is an ${existing.protocol.toUpperCase()} share — enter an ${existing.protocol.toUpperCase()} address, or add a new share instead.`);
    }
    setSubmitting(true);
    try {
      const versionOut = versionValue === "auto" ? "" : versionValue;
      const login = smb ? { username, domain } : {};
      if (editing) {
        await updateShare(existing.id, {
          location,
          ...login,
          version: versionOut,
          ...(smb && password ? { password } : {}), // blank keeps the saved password
        });
      } else {
        await createShare({ name, location, ...login, password: smb ? password || null : null, version: versionOut });
      }
      await onSaved();
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="e.g. Lab NAS" disabled={editing} />
      <TextField
        label="NAS folder address"
        value={location}
        onChange={setLocation}
        placeholder="e.g. //192.168.1.50/farmhand/Projects   or   192.168.1.50:/volume1/farmhand"
      />
      <div data-testid="location-preview" style={{ ...ui, fontSize: fs(12), lineHeight: 1.5, marginTop: -6, marginBottom: 14, color: described ? (described.ok ? c.teal : c.amber) : c.textFaint }}>
        {described
          ? described.text
          : "Paste the folder's full address — Farmhand works out the rest. SMB (//server/share) and NFS (server:/export) both work."}
      </div>
      {capability?.[`${protocol}_message`] && (
        <div data-testid="protocol-unavailable" style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.6, border: `1px solid ${c.amber}`, background: c.amberDim, borderRadius: 4, padding: "9px 12px", marginBottom: 14 }}>
          {capability[`${protocol}_message`]}
        </div>
      )}
      {smb && (
        <>
          <TextField label="Username (leave blank for guest access)" value={username} onChange={setUsername} placeholder="e.g. alice" />
          <TextField
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder={editing && existing.hasPassword ? "Leave blank to keep the saved password" : ""}
          />
          <TextField label="Domain / workgroup (optional)" value={domain} onChange={setDomain} placeholder="" />
        </>
      )}
      <FieldSelect
        label={`${smb ? "SMB" : "NFS"} version (advanced)`}
        placeholder="Choose…"
        value={versionValue}
        onChange={setVersion}
        options={
          smb
            ? [
                { value: "auto", label: "Automatic (recommended)" },
                { value: "3.1.1", label: "3.1.1" },
                { value: "3.0", label: "3.0" },
                { value: "2.1", label: "2.1" },
              ]
            : [
                { value: "4", label: "4 (recommended)" },
                { value: "3", label: "3" },
              ]
        }
      />
      <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, marginBottom: 14, lineHeight: 1.5 }}>
        Farmhand connects right now and only saves the share if that works. The login is kept in Farmhand's database so
        it can reconnect after a restart; it's never shown again.
      </div>
      <ModalActions
        onClose={onClose}
        onSubmit={handleSubmit}
        actionLabel={editing ? "Save" : "Connect"}
        submittingLabel={editing ? "Saving…" : "Connecting…"}
        submitting={submitting}
        errorMsg={errorMsg}
      />
    </>
  );
}

function SharesCard({ data, onAdd, onEdit, onReconnect, onRemove, busyId, actionError }) {
  const { shares, capability } = data;
  const btn = { ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "4px 10px", cursor: "pointer" };
  return (
    <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div style={{ ...ui, fontSize: fs(15), color: c.heading }}>Network shares</div>
        <button
          onClick={onAdd}
          disabled={!capability.ok}
          style={{ display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(13), background: capability.ok ? c.amberDim : "none", color: capability.ok ? c.amber : c.textFaint, border: `1px solid ${capability.ok ? c.amber : c.border}`, borderRadius: 4, padding: "6px 12px", cursor: capability.ok ? "pointer" : "not-allowed" }}
        >
          <Server size={13} />
          Add network share…
        </button>
      </div>
      <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 12 }}>
        Connect your NAS here. Farmhand mounts it itself and reconnects after restarts — then choose folders on it below.
      </div>

      {!capability.ok && (
        <div data-testid="capability-warning" style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.6, border: `1px solid ${c.amber}`, background: c.amberDim, borderRadius: 4, padding: "10px 12px", marginBottom: 12 }}>
          {capability.message}
        </div>
      )}

      {capability.ok && (capability.smb_message || capability.nfs_message) && (
        <div data-testid="capability-partial" style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.6, border: `1px solid ${c.amber}`, background: c.amberDim, borderRadius: 4, padding: "10px 12px", marginBottom: 12 }}>
          {capability.smb_message && <div><b>SMB shares:</b> {capability.smb_message}</div>}
          {capability.nfs_message && <div><b>NFS shares:</b> {capability.nfs_message}</div>}
        </div>
      )}

      {shares.length === 0 && capability.ok && (
        <div style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>No network shares yet.</div>
      )}

      {shares.map((sh, i) => (
        <div key={sh.id} style={{ borderTop: i === 0 ? "none" : `1px solid ${c.border}`, padding: "10px 0" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ ...ui, fontSize: fs(14), color: c.heading, display: "flex", alignItems: "center", gap: 8 }}>
                <Server size={14} color={c.textFaint} />
                {sh.name}
                {sh.mounted ? <Badge tone="green">connected</Badge> : <Badge tone="amber">not connected</Badge>}
              </div>
              <div style={{ ...mono, fontSize: fs(11), color: c.textFaint, marginTop: 3, wordBreak: "break-all" }}>
                {sh.address}
                {sh.username ? ` · ${sh.username}` : sh.protocol === "smb" ? " · guest" : ""}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
              {!sh.mounted && (
                <button onClick={() => onReconnect(sh)} disabled={busyId === sh.id} style={btn}>
                  {busyId === sh.id ? "Connecting…" : "Reconnect"}
                </button>
              )}
              <button onClick={() => onEdit(sh)} style={btn}>
                Edit
              </button>
              <button onClick={() => onRemove(sh)} style={btn}>
                Remove
              </button>
            </div>
          </div>
          {!sh.mounted && sh.error && (
            <div style={{ ...ui, fontSize: fs(12), color: c.amber, marginTop: 6, lineHeight: 1.5 }}>{sh.error}</div>
          )}
          {!sh.mounted && !sh.error && (
            <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginTop: 6 }}>
              Farmhand will keep trying to connect to this in the background.
            </div>
          )}
        </div>
      ))}
      {actionError && <div style={{ ...ui, fontSize: fs(12), color: c.amber, marginTop: 8, lineHeight: 1.5 }}>{actionError}</div>}
    </div>
  );
}

// Where the copy of Farmhand's settings is kept on the network (the server also keeps them itself)
function ConfigLocationCard({ info, onChoose, onSaveNow, onRestore, onClear, error }) {
  const btn = { ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.borderStrong}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" };
  const set = info?.isSet;
  const status = info?.status;
  const problem = !set ? null : !status.exists ? "Folder not found" : !status.writable ? "Not writable" : !status.markerOk ? "Marker missing — the share may be unmounted" : null;
  const when = (iso) => (iso ? new Date(iso).toLocaleString() : null);
  const lastError = info?.lastWrite && info.lastWrite.ok === false ? info.lastWrite.error : null;

  return (
    <div data-testid="config-card" style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div style={{ ...ui, fontSize: fs(15), color: c.heading }}>Settings location</div>
        <div style={{ display: "flex", gap: 6 }}>
          <Badge tone={set ? "teal" : "muted"}>{set ? "network folder" : "server only"}</Badge>
          {set && (problem ? <Badge tone="amber">{problem}</Badge> : <Badge tone="green">ready</Badge>)}
        </div>
      </div>
      <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, lineHeight: 1.6, marginBottom: 12 }}>
        Farmhand keeps its settings on the server: the look of the site, display preferences, your storage and share setup,
        your printers (with their notes, 1500-hour service, print history and energy readings) and the notes on your models
        and 3MF files. Choose a folder on the network and a copy is written there after every change, so they survive a
        rebuild and can be restored. Passwords and Moonraker API keys are never written to it.
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", border: `1px solid ${c.border}`, borderRadius: 4, background: c.panelAlt, marginBottom: 10 }}>
        <HardDrive size={15} color={c.textFaint} />
        <span data-testid="config-path" style={{ ...mono, fontSize: fs(12), color: set ? c.heading : c.textFaint, wordBreak: "break-all" }}>
          {set ? info.path : "No network folder chosen — settings are kept on the server only"}
        </span>
      </div>

      {set && (
        <div data-testid="config-file" style={{ ...ui, fontSize: fs(12), color: c.textFaint, marginBottom: 10 }}>
          {info.file?.exists ? (
            <>
              <span style={mono}>farmhand-config.json</span> — last written {when(info.file.modifiedAt)}. Next to it, a file per
              printer in <span style={mono}>printers/</span> and per model in <span style={mono}>models/</span>.
            </>
          ) : (
            <>No settings file in this folder yet.</>
          )}
        </div>
      )}
      {lastError && (
        <div data-testid="config-error" style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.5, marginBottom: 10 }}>
          The last copy couldn't be written: {lastError} Your settings are still safe on the server.
        </div>
      )}
      {error && <div style={{ ...ui, fontSize: fs(12), color: c.amber, lineHeight: 1.5, marginBottom: 10 }}>{error}</div>}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button data-testid="config-choose" onClick={onChoose} style={btn}>
          {set ? "Change folder…" : "Choose folder…"}
        </button>
        {set && (
          <button data-testid="config-save-now" onClick={onSaveNow} style={btn}>
            Save a copy now
          </button>
        )}
        {set && info.file?.exists && (
          <button data-testid="config-restore" onClick={onRestore} style={btn}>
            Restore from this folder…
          </button>
        )}
        {set && (
          <button data-testid="config-clear" onClick={onClear} style={{ ...btn, color: c.textFaint, borderColor: c.border }}>
            Use the server only
          </button>
        )}
      </div>
    </div>
  );
}

// What a restore did, in plain words
function RestoreResult({ result }) {
  const list = (names) => names.join(", ");
  return (
    <div data-testid="config-restore-result" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 14, ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.7 }}>
      <div style={{ color: c.heading, marginBottom: 4 }}>Restored: {list(result.restored)}.</div>
      {result.sharesAdded.length > 0 && <div>Network shares added: {list(result.sharesAdded)}. They connect in the background.</div>}
      {result.sharesKept.length > 0 && <div>Already here, kept as they were: {list(result.sharesKept)}.</div>}
      {result.needsPassword.length > 0 && (
        <div style={{ color: c.amber }}>
          Needs its password (passwords are never saved in the settings): {list(result.needsPassword)}. Use Edit on the share above.
        </div>
      )}
      {result.records && <RestoredRecords r={result.records} list={list} />}
      {result.warnings.map((w) => (
        <div key={w} style={{ color: c.amber }}>{w}</div>
      ))}
    </div>
  );
}

// What came back from the printers/ and models/ files (restoring only ever adds what was missing)
function RestoredRecords({ r, list }) {
  const n = (count, one, many) => `${count.toLocaleString()} ${count === 1 ? one : many}`;
  const notes = [
    r.modelNotes && n(r.modelNotes, "model's notes", "models' notes"),
    r.threemfNotes && n(r.threemfNotes, "3MF file's notes", "3MF files' notes"),
    r.stars && n(r.stars, "starred version", "starred versions"),
  ].filter(Boolean);
  return (
    <>
      {r.printersAdded.length > 0 && <div>Printers added: {list(r.printersAdded)}.</div>}
      {r.printersFilled.length > 0 && <div>Printers already here, with what they were missing filled in: {list(r.printersFilled)}.</div>}
      {(r.printsAdded > 0 || r.readingsAdded > 0) && (
        <div>
          Brought back {n(r.printsAdded, "print", "prints")} from the history and {n(r.readingsAdded, "power meter reading", "power meter readings")}.
        </div>
      )}
      {notes.length > 0 && <div>Notes put back: {notes.join(", ")}.</div>}
      {r.modelsMissing.length > 0 && (
        <div style={{ color: c.textFaint }}>
          Notes kept for models that aren't in Farmhand (they go back once the model is added again and you restore): {list(r.modelsMissing)}.
        </div>
      )}
    </>
  );
}

// Appearance has its own page (a menu item below Storage). It only needs to know whether a settings folder is
// chosen, to say where a change was kept.
function AppearancePage({ appearance, saved, onChange, onSave, onDiscard, saveState }) {
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

function StorageSection({ onSettingsRestored }) {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [picker, setPicker] = useState(null); // null | "stl" | "threemf"
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveResult, setMoveResult] = useState(null);
  const [sharesInfo, setSharesInfo] = useState(null);
  const [shareForm, setShareForm] = useState(null); // null | { existing?: share }
  const [removing, setRemoving] = useState(null); // null | share
  const [shareBusy, setShareBusy] = useState(null);
  const [shareError, setShareError] = useState(null);
  const [configInfo, setConfigInfo] = useState(null); // where the settings copy goes
  const [configPicker, setConfigPicker] = useState(false);
  const [configFound, setConfigFound] = useState(null); // the folder just chosen already holds a settings file
  const [configRestoreOpen, setConfigRestoreOpen] = useState(false);
  const [configResult, setConfigResult] = useState(null);
  const [configBusy, setConfigBusy] = useState(false);
  const [configError, setConfigError] = useState(null);

  useEffect(() => {
    Promise.all([getStorageSettings(), getShares(), getConfig().catch(() => null)])
      .then(([storageInfo, sharesData, config]) => {
        setInfo(storageInfo);
        setSharesInfo(sharesData);
        setConfigInfo(config ? config.location : null);
      })
      .catch((e) => setError(e.message || String(e)));
  }, []);

  if (error) {
    return <div style={{ ...ui, fontSize: fs(13), color: c.amber }}>Couldn't load storage settings: {error}</div>;
  }
  if (!info || !sharesInfo) {
    return <div style={{ ...ui, fontSize: fs(13), color: c.textFaint }}>Loading storage settings…</div>;
  }

  // Shares and the storage locations affect each other (a share's files, what's "ready"), so refresh both
  const reloadAll = async () => {
    const [storageInfo, sharesData] = await Promise.all([getStorageSettings(), getShares()]);
    setInfo(storageInfo);
    setSharesInfo(sharesData);
  };
  const refreshConfigInfo = async () => {
    try {
      setConfigInfo((await getConfig()).location);
    } catch {
      /* leave what's shown */
    }
  };
  const chooseConfigFolder = async (path) => {
    setConfigError(null);
    const found = await inspectConfigFolder(path); // refuses (with the reason) a folder that can't be used
    if (found.fileExists) {
      setConfigFound(found); // never overwrite settings that are already there without being told to
      return;
    }
    setConfigInfo((await setConfigLocation({ path })).location);
  };
  const resolveFound = async (choice) => {
    setConfigBusy(true);
    setConfigError(null);
    try {
      const r = await setConfigLocation({ path: configFound.path, ifExists: choice });
      setConfigInfo(r.location);
      if (r.restored) {
        setConfigResult(r.restored);
        onSettingsRestored();
        await reloadAll();
      }
      setConfigFound(null);
    } catch (e) {
      setConfigError(e.message || String(e));
    } finally {
      setConfigBusy(false);
    }
  };
  const clearConfigFolder = async () => {
    setConfigError(null);
    setConfigInfo((await setConfigLocation({ path: null })).location);
  };
  const saveConfigCopyNow = async () => {
    setConfigError(null);
    try {
      const r = await saveConfigNow();
      if (!r.ok) setConfigError(r.error);
    } catch (e) {
      setConfigError(e.message || String(e));
    }
    await refreshConfigInfo();
  };
  const reconnect = async (sh) => {
    setShareError(null);
    setShareBusy(sh.id);
    try {
      await reconnectShare(sh.id);
    } catch (e) {
      setShareError(`${sh.name}: ${e.message || e}`);
    } finally {
      setShareBusy(null);
      await reloadAll().catch(() => {});
    }
  };

  const body = (kind, path) => (kind === "stl" ? { stlPath: path } : { threemfPath: path });
  const resetLocation = async (kind) => {
    setActionError(null);
    try {
      setInfo(await saveStorageSettings(body(kind, null)));
    } catch (e) {
      setActionError(e.message || String(e));
    }
  };
  const outsideStl = info.outside.stl;
  const outsideThreemf = info.outside.threemf;
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 820 }}>
      <SectionLabel>Where files are stored</SectionLabel>

      <SharesCard
        data={sharesInfo}
        onAdd={() => setShareForm({})}
        onEdit={(sh) => setShareForm({ existing: sh })}
        onReconnect={reconnect}
        onRemove={async (sh) => {
          setShareError(null);
          try {
            const fresh = await getShares();
            setSharesInfo(fresh);
            setRemoving(fresh.shares.find((x) => x.id === sh.id) || sh);
          } catch {
            setRemoving(sh);
          }
        }}
        busyId={shareBusy}
        actionError={shareError}
      />

      <LocationCard
        title="STL / OBJ / STEP files"
        blurb="The source model files in the Models library."
        location={info.stl}
        onChange={() => setPicker("stl")}
        onReset={() => resetLocation("stl")}
      />
      <LocationCard
        title="3MF and gcode files"
        blurb="The sliced bundles and their gcode."
        location={info.threemf}
        onChange={() => setPicker("threemf")}
        onReset={() => resetLocation("threemf")}
      />
      {actionError && <div style={{ ...ui, fontSize: fs(12), color: c.amber }}>{actionError}</div>}

      {outsideStl + outsideThreemf > 0 && (
        <div style={{ border: `1px solid ${c.borderStrong}`, borderRadius: 4, background: c.panelAlt, padding: 16 }}>
          <div style={{ ...ui, fontSize: fs(13), color: c.textPrimary, marginBottom: 6 }}>
            {[
              outsideStl > 0 && plural(outsideStl, "STL version", "STL versions"),
              outsideThreemf > 0 && plural(outsideThreemf, "3MF version", "3MF versions"),
            ]
              .filter(Boolean)
              .join(" and ")}{" "}
            still {outsideStl + outsideThreemf === 1 ? "has" : "have"} files in a previous location.
          </div>
          <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, lineHeight: 1.6, marginBottom: 12 }}>
            They keep working where they are — only new uploads use the locations above. Moving copies each file into its
            chosen location, checks the copy, and only then removes the original.
          </div>
          <button
            onClick={() => setMoveOpen(true)}
            style={{ ...ui, fontSize: fs(13), background: c.amber, color: c.onAccent, border: "none", borderRadius: 4, padding: "7px 14px", fontWeight: 600, cursor: "pointer" }}
          >
            Move them now…
          </button>
        </div>
      )}

      {moveResult && (
        <div data-testid="move-result" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 14, ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6 }}>
          Moved {plural(moveResult.movedStl, "STL version", "STL versions")} and{" "}
          {plural(moveResult.movedThreemf, "3MF version", "3MF versions")}.
          {moveResult.missing.length > 0 && (
            <div style={{ color: c.amber, marginTop: 6 }}>
              Not found on disk (skipped): <span style={mono}>{moveResult.missing.join(", ")}</span>
            </div>
          )}
          {moveResult.failed.map((f) => (
            <div key={f.name} style={{ color: c.amber, marginTop: 6 }}>
              Couldn't move <span style={mono}>{f.name}</span>: {f.error}
            </div>
          ))}
        </div>
      )}

      <div style={{ ...ui, fontSize: fs(12), color: c.textFaint, lineHeight: 1.7 }}>
        <div>
          <b style={{ color: c.textMuted }}>Network shares.</b> Farmhand mounts them itself, so there's nothing to set up on
          the computer running it. To do that its container is given the SYS_ADMIN and DAC_READ_SEARCH permissions (see the README).
        </div>
        <div style={{ marginTop: 6 }}>
          <b style={{ color: c.textMuted }}>Safety check.</b> Chosen folders get a small <span style={mono}>.farmhand-storage</span>{" "}
          marker. If a share drops and leaves an empty folder behind, the marker is missing and uploads are refused rather
          than silently filling the local disk.
        </div>
        <div style={{ marginTop: 6 }}>
          <b style={{ color: c.textMuted }}>Thumbnails</b> always stay on the app's local disk, so browsing keeps working
          if a share is offline.
        </div>
      </div>

      <SectionLabel>Settings</SectionLabel>
      <ConfigLocationCard
        info={configInfo}
        error={configError}
        onChoose={() => setConfigPicker(true)}
        onSaveNow={saveConfigCopyNow}
        onRestore={() => setConfigRestoreOpen(true)}
        onClear={clearConfigFolder}
      />
      {configResult && <RestoreResult result={configResult} />}

      {configPicker && (
        <FolderPicker
          title="Choose the folder for Farmhand's settings"
          startPath={configInfo?.isSet ? configInfo.path : null}
          shares={sharesInfo.shares}
          onSelect={chooseConfigFolder}
          onClose={() => setConfigPicker(false)}
        />
      )}

      {configFound && (
        <Modal title="Settings already in that folder" onClose={() => (configBusy ? undefined : setConfigFound(null))} width={580}>
          <div data-testid="config-found" style={{ ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6, marginBottom: 14 }}>
            {configFound.fileValid ? (
              <>
                That folder already has a Farmhand settings file
                {configFound.summary?.savedAt ? <> (saved {new Date(configFound.summary.savedAt).toLocaleString()})</> : null}: colour scheme{" "}
                <b style={{ color: c.heading }}>{configFound.summary?.scheme}</b>
                {configFound.summary?.shares ? `, ${configFound.summary.shares} network share${configFound.summary.shares === 1 ? "" : "s"}` : ""}
                {configFound.summary?.printers ? `, ${configFound.summary.printers} printer${configFound.summary.printers === 1 ? "" : "s"}` : ""}
                {configFound.summary?.models ? `, notes for ${configFound.summary.models} model${configFound.summary.models === 1 ? "" : "s"}` : ""}. What
                should Farmhand do with it?
              </>
            ) : (
              <>
                That folder has a settings file Farmhand can't use: <span style={{ color: c.amber }}>{configFound.error}</span> It can be
                replaced with the current settings, or you can pick another folder.
              </>
            )}
          </div>
          {configError && <div style={{ ...ui, fontSize: fs(12), color: c.amber, marginBottom: 10 }}>{configError}</div>}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
            <button
              onClick={() => setConfigFound(null)}
              disabled={configBusy}
              style={{ ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "7px 14px", cursor: "pointer" }}
            >
              Cancel
            </button>
            <button
              data-testid="config-found-overwrite"
              onClick={() => resolveFound("overwrite")}
              disabled={configBusy}
              style={{ ...ui, fontSize: fs(13), background: "none", color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 3, padding: "7px 14px", cursor: "pointer" }}
            >
              Replace with current settings
            </button>
            {configFound.fileValid && (
              <button
                data-testid="config-found-restore"
                onClick={() => resolveFound("restore")}
                disabled={configBusy}
                style={{ ...ui, fontSize: fs(13), background: c.amber, color: c.onAccent, border: "none", borderRadius: 3, padding: "7px 14px", fontWeight: 600, cursor: "pointer" }}
              >
                {configBusy ? "Working…" : "Use those settings"}
              </button>
            )}
          </div>
        </Modal>
      )}

      {configRestoreOpen && (
        <ConfirmDialog
          title="Restore settings from the network folder"
          confirmLabel="Restore"
          tone="primary"
          onClose={() => setConfigRestoreOpen(false)}
          onConfirm={async () => {
            const result = await restoreConfig();
            setConfigResult(result);
            onSettingsRestored();
            await reloadAll();
          }}
        >
          <div>
            Load the settings saved in that folder? This replaces the current look and display preferences with the saved
            ones, puts back the STL and 3MF folders it lists, and adds any network shares that aren't already here. Passwords
            aren't saved, so those shares will need theirs typed in.
          </div>
        </ConfirmDialog>
      )}

      {picker && (
        <FolderPicker
          title={picker === "stl" ? "Choose the folder for STL files" : "Choose the folder for 3MF files"}
          startPath={(picker === "stl" ? info.stl : info.threemf).isDefault ? null : (picker === "stl" ? info.stl : info.threemf).path}
          shares={sharesInfo.shares}
          onSelect={async (path) => setInfo(await saveStorageSettings(body(picker, path)))}
          onClose={() => setPicker(null)}
        />
      )}

      {shareForm && (
        <Modal title={shareForm.existing ? `Edit ${shareForm.existing.name}` : "Add network share"} onClose={() => setShareForm(null)} width={500}>
          <ShareForm
            existing={shareForm.existing}
            capability={sharesInfo.capability}
            onClose={() => setShareForm(null)}
            onSaved={reloadAll}
          />
        </Modal>
      )}

      {removing && (
        <ConfirmDialog
          title="Remove network share"
          confirmLabel="Remove share"
          onClose={() => setRemoving(null)}
          onConfirm={async () => {
            await deleteShare(removing.id);
            await reloadAll();
          }}
        >
          <div>
            Disconnect <b style={{ color: c.heading }}>{removing.name}</b> and forget its login? Nothing on the NAS is
            deleted.
          </div>
          {removing.filesHere > 0 && (
            <DeleteWarning>
              {removing.filesHere === 1 ? "1 version has its files" : `${removing.filesHere} versions have their files`} stored
              on this share. Farmhand won't be able to open or download them until you add the share again.
            </DeleteWarning>
          )}
        </ConfirmDialog>
      )}

      {moveOpen && (
        <ConfirmDialog
          title="Move files to the chosen locations"
          confirmLabel="Move files"
          tone="primary"
          onClose={() => setMoveOpen(false)}
          onConfirm={async () => {
            setMoveResult(await migrateStorage());
            await reloadAll(); // locations AND shares: how many files live on each share just changed
          }}
        >
          <div>
            Move {[outsideStl > 0 && plural(outsideStl, "STL version", "STL versions"), outsideThreemf > 0 && plural(outsideThreemf, "3MF version", "3MF versions")].filter(Boolean).join(" and ")}{" "}
            into the locations above? Large files over a network can take a while — keep this page open until it finishes.
          </div>
        </ConfirmDialog>
      )}
    </div>
  );
}

// `npm run mock`: the real UI on built-in sample data (frontend/mock/). Said plainly in the sidebar, so the mockup
// is never mistaken for the real farm, with a way back to the untouched sample data.
const MOCKUP = !!import.meta.env.VITE_MOCK;
function MockupBadge() {
  const [busy, setBusy] = useState(false);
  return (
    <div data-testid="mockup-badge" style={{ margin: "14px 4px 0", border: `1px dashed ${c.amber}`, borderRadius: 4, padding: "10px 12px", background: c.amberDim }}>
      <div style={{ ...ui, fontSize: fs(12), fontWeight: 600, color: c.amber, marginBottom: 4 }}>Mockup</div>
      <div style={{ ...ui, fontSize: fs(11), color: c.textMuted, lineHeight: 1.5, marginBottom: 8 }}>
        Sample data, no real farm. Changes last until the mockup restarts.
      </div>
      <button
        data-testid="mockup-reset"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await fetch(`${API_BASE}/__reset`, { method: "POST" });
          window.location.reload();
        }}
        style={{ ...ui, fontSize: fs(11), background: "none", color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 3, padding: "3px 8px", cursor: busy ? "default" : "pointer" }}
      >
        {busy ? "Resetting…" : "Reset sample data"}
      </button>
    </div>
  );
}

function CompareTray({ selection, onRemove, onCompare, onClear }) {
  const { versionIndex, versionLabel } = useData();
  if (selection.length === 0) return null;
  return (
    <div
      data-testid="compare-tray"
      style={{
        position: "fixed",
        left: 220,
        right: 0,
        bottom: 0,
        background: c.panel,
        borderTop: `1px solid ${c.borderStrong}`,
        padding: "12px 24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        zIndex: 40,
        boxShadow: "0 -4px 16px rgba(0,0,0,0.3)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", flex: 1, minWidth: 0 }}>
        <span style={{ ...ui, fontSize: fs(12), color: c.textFaint, flexShrink: 0 }}>
          Selected for compare ({selection.length}):
        </span>
        {selection.map((id, i) => {
          const entry = versionIndex[id];
          if (!entry) return null;
          return (
            <div
              key={id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                border: `1px solid ${i === 0 ? c.amber : i === 1 ? c.teal : c.border}`,
                background: i === 0 ? c.amberDim : i === 1 ? c.tealDim : c.panelAlt,
                borderRadius: 3,
                padding: "4px 8px",
              }}
            >
              <span data-testid="compare-chip" style={{ ...mono, fontSize: fs(11), color: c.textPrimary }}>{versionLabel(entry)}</span>
              <button
                onClick={() => onRemove(id)}
                title="Unselect"
                style={{ background: "none", border: "none", color: c.textFaint, cursor: "pointer", padding: 0, display: "flex" }}
              >
                <X size={12} />
              </button>
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <button
          onClick={onClear}
          style={{
            ...ui,
            fontSize: fs(12),
            background: "none",
            color: c.textFaint,
            border: "none",
            cursor: "pointer",
            padding: "6px 4px",
          }}
        >
          Clear
        </button>
        {selection.length >= 2 && (
          <button
            data-testid="compare-go"
            onClick={onCompare}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              ...ui,
              fontSize: fs(13),
              background: c.amber,
              color: c.onAccent,
              border: "none",
              borderRadius: 4,
              padding: "8px 14px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            <GitCompare size={13} />
            Compare
          </button>
        )}
      </div>
    </div>
  );
}

function FarmhandApp() {
  const { printers, sourceModels, bundles, bundleTitle, versionIndex, loading, error, refresh } = useData();
  const [section, setSection] = useState("models"); // 'printers' | 'models'
  const [printerPath, setPrinterPath] = useState([{ label: "Printers" }]);
  const [modelPath, setModelPath] = useState([{ label: "Models" }]);
  // Appearance: colour scheme, text brightness, font and size. Held HERE (not in a provider above) so that a
  // change re-renders everything below: components read the live theme (theme.js) as they render.
  // The server keeps these (so every browser and device shows the same look), and copies them to the network
  // folder chosen on the Storage page. What this browser remembers is only used to paint the right look at
  // once, before the server has answered.
  const [appearance, setAppearance] = useState(loadAppearance); // the SAVED look
  const [preview, setPreview] = useState(null); // a look being tried on the Appearance page, not saved yet (null = none)
  const [modelSort, setModelSort] = useState(loadModelSort);
  const [saveState, setSaveState] = useState({ phase: "idle" }); // idle | saving | saved | error
  const pendingSave = useRef({});
  const saveTimer = useRef(null);
  applyAppearance(preview || appearance); // a preview shows live; it only becomes the saved look when Save is pressed

  // Changes the server hasn't confirmed yet are also written down in this browser. If the page is closed, or the
  // server is unreachable, they're sent on the next visit instead of being overwritten by the server's older copy.
  const rememberPending = (patch) => {
    try {
      if (patch && Object.keys(patch).length) localStorage.setItem(PENDING_CONFIG_KEY, JSON.stringify(patch));
      else localStorage.removeItem(PENDING_CONFIG_KEY);
    } catch {
      /* storage unavailable */
    }
  };

  const adoptServerConfig = (config) => {
    const a = normalizeAppearance(config.appearance);
    const sort = normalizeModelSort(config.preferences?.model_sort);
    setAppearance(a);
    saveAppearance(a);
    setModelSort(sort);
    saveModelSort(sort);
  };
  const loadServerConfig = () =>
    getConfig()
      .then(({ config }) => adoptServerConfig(config))
      .catch(() => {
        /* the server isn't answering: carry on with what this browser remembers */
      });
  useEffect(() => {
    let pending = null;
    try {
      pending = JSON.parse(localStorage.getItem(PENDING_CONFIG_KEY));
    } catch {
      /* nothing waiting */
    }
    if (pending && Object.keys(pending).length) {
      // changes made here that never reached the server: send them first, then show what the server now holds
      saveConfig(pending)
        .then((r) => {
          rememberPending(null);
          adoptServerConfig(r.config);
        })
        .catch(() => {
          /* still can't reach it: keep them for next time and carry on with what this browser remembers */
        });
    } else {
      loadServerConfig();
    }
    // closing or leaving the page within the short wait below must not lose the last change
    const onHide = () => {
      if (Object.keys(pendingSave.current).length) saveConfigOnExit(pendingSave.current);
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, []);

  const flushSave = async () => {
    const patch = pendingSave.current;
    pendingSave.current = {};
    try {
      const result = await saveConfig(patch);
      rememberPending(pendingSave.current); // anything changed while that was in flight is still waiting
      setSaveState({ phase: "saved", mirror: result.mirror });
    } catch (e) {
      pendingSave.current = { ...patch, ...pendingSave.current }; // not delivered: keep it, newer values winning
      rememberPending(pendingSave.current);
      setSaveState({ phase: "error", message: e.message || String(e) });
    }
  };
  // A slider drags through many values: wait for it to settle rather than rewriting the network file for each
  const queueSave = (patch, { immediate = false } = {}) => {
    pendingSave.current = { ...pendingSave.current, ...patch };
    rememberPending(pendingSave.current);
    setSaveState({ phase: "saving" });
    clearTimeout(saveTimer.current);
    if (immediate) flushSave();
    else saveTimer.current = setTimeout(flushSave, 400);
  };

  // Appearance: changes are a live PREVIEW until Save is pressed. Leaving the page without saving undoes them.
  const sameLook = (a, b) =>
    a.scheme === b.scheme && a.contrast === b.contrast && a.font === b.font && a.size === b.size && a.file_name_color === b.file_name_color;
  const changeAppearance = (next) => setPreview(sameLook(next, appearance) ? null : next);
  const discardAppearance = () => setPreview(null);
  const commitAppearance = () => {
    if (!preview) return;
    const next = preview;
    setAppearance(next);
    saveAppearance(next);
    setPreview(null);
    queueSave({ appearance: next }, { immediate: true });
  };
  const changeModelSort = (next) => {
    setModelSort(next);
    saveModelSort(next);
    queueSave({ preferences: { model_sort: next } });
  };
  const [compareSelection, setCompareSelection] = useState([]); // VERSION ids, in selection order
  const [diffModalOpen, setDiffModalOpen] = useState(false);

  // If what we're looking at gets deleted (a model folder, a printer), fall back
  // to the list instead of rendering a page for something that no longer exists.
  // (These hooks must stay above the early returns below.)
  const modelPathSafe = modelPath.every((seg) => seg.modelId == null || sourceModels.some((m) => m.id === seg.modelId))
    ? modelPath
    : [{ label: "Models" }];
  const printerPathSafe = printerPath.every(
    (seg) =>
      (seg.printerId == null || printers.some((p) => p.id === seg.printerId)) &&
      (seg.bundleId == null || bundles.some((b) => b.id === seg.bundleId))
  )
    ? printerPath
    : [{ label: "Printers" }];

  useEffect(() => {
    if (modelPathSafe !== modelPath) setModelPath(modelPathSafe);
  }, [modelPathSafe, modelPath]);
  useEffect(() => {
    if (printerPathSafe !== printerPath) setPrinterPath(printerPathSafe);
  }, [printerPathSafe, printerPath]);

  // Drop deleted versions from the compare selection
  useEffect(() => {
    setCompareSelection((prev) => {
      const next = prev.filter((id) => versionIndex[id]);
      if (next.length === prev.length) return prev;
      setDiffModalOpen(false);
      return next;
    });
  }, [versionIndex]);

  if (loading) {
    return (
      <div style={{ ...ui, display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: c.bg, color: c.textFaint }}>
        Loading Farmhand…
      </div>
    );
  }
  if (error) {
    return (
      <div style={{ ...ui, display: "flex", flexDirection: "column", gap: 12, alignItems: "center", justifyContent: "center", height: "100vh", background: c.bg, color: c.amber, padding: 24, textAlign: "center" }}>
        <div>Couldn't reach the API: {error}</div>
        <div style={{ color: c.textFaint, fontSize: fs(13) }}>Checked {API_BASE} — is the backend running?</div>
        <button
          onClick={refresh}
          style={{ ...ui, fontSize: fs(13), background: c.amberDim, color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 4, padding: "7px 14px", cursor: "pointer" }}
        >
          Retry
        </button>
      </div>
    );
  }

  const toggleCompareSelect = (versionId) => {
    // A compare is between two versions: picking a third replaces the oldest pick instead of being ignored
    setCompareSelection((prev) =>
      prev.includes(versionId)
        ? prev.filter((id) => id !== versionId)
        : prev.length >= 2
          ? [prev[1], versionId]
          : [...prev, versionId]
    );
    setDiffModalOpen(false);
  };
  const removeFromCompare = (versionId) => {
    setCompareSelection((prev) => prev.filter((id) => id !== versionId));
    setDiffModalOpen(false);
  };
  const clearCompare = () => {
    setCompareSelection([]);
    setDiffModalOpen(false);
  };

  const path =
    section === "printers" ? printerPathSafe : section === "models" ? modelPathSafe : [{ label: section === "appearance" ? "Appearance" : "Storage" }];
  const setPath = section === "printers" ? setPrinterPath : section === "models" ? setModelPath : () => {};
  const diffLeft = versionIndex[compareSelection[0]];
  const diffRight = versionIndex[compareSelection[1]];

  const crumbLabels = path.map((seg, i) => {
    if (seg.label) return seg.label;
    if (section === "printers") {
      const printer = printers.find((p) => p.id === seg.printerId);
      if (seg.bundleId) {
        const bundle = bundles.find((b) => b.id === seg.bundleId);
        return bundleTitle(bundle);
      }
      return printer.name;
    } else {
      const model = sourceModels.find((m) => m.id === seg.modelId);
      return model.name;
    }
  });

  const navItem = (key, label, Icon, count) => (
    <button
      onClick={() => {
        if (key !== "appearance") setPreview(null); // an unsaved preview is undone when you leave the page
        setSection(key);
        if (key === "printers") setPrinterPath([{ label: "Printers" }]);
        else if (key === "models") setModelPath([{ label: "Models" }]);
      }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "9px 14px",
        borderRadius: 4,
        border: "none",
        background: section === key ? c.panelAlt : "transparent",
        color: section === key ? c.textPrimary : c.textMuted,
        cursor: "pointer",
        ...ui,
        fontSize: fs(14),
        textAlign: "left",
        marginBottom: 2,
      }}
    >
      <Icon size={16} color={section === key ? c.amber : c.textFaint} />
      <span style={{ flex: 1 }}>{label}</span>
      <span style={{ ...mono, fontSize: fs(11), color: c.textFaint }}>{count}</span>
    </button>
  );

  return (
    <div
      style={{
        ...ui,
        display: "flex",
        height: "100vh",
        background: c.bg,
        color: c.textPrimary,
      }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; }
      `}</style>

      {/* Sidebar */}
      <div
        style={{
          width: 220,
          borderRight: `1px solid ${c.border}`,
          background: c.panel,
          padding: 16,
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 24, padding: "0 4px" }}>
          <Archive size={18} color={c.amber} />
          <span style={{ fontSize: fs(15), fontWeight: 600, letterSpacing: 0.2, color: c.heading }}>Farmhand</span>
        </div>
        {navItem("models", "Models", Layers, sourceModels.length)}
        {navItem("printers", "Printers", Printer, printers.length)}
        {navItem("storage", "Storage", HardDrive, "")}
        {navItem("appearance", "Appearance", Palette, "")}
        <div style={{ borderTop: `1px solid ${c.border}`, marginTop: 12, paddingTop: 12 }}>
          <div style={{ fontSize: fs(11), color: c.textFaint, padding: "0 14px", lineHeight: 1.6 }}>
            Read-only archive. Nothing here re-slices or sends jobs to a printer.
          </div>
        </div>
        {MOCKUP && <MockupBadge />}
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div
          style={{
            padding: "16px 24px",
            borderBottom: `1px solid ${c.border}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Crumb items={crumbLabels} onJump={(i) => setPath(path.slice(0, i + 1))} />
        </div>
        <div style={{ padding: 24, paddingBottom: compareSelection.length > 0 ? 80 : 24, overflow: "auto", flex: 1 }}>
          {section === "printers" ? (
            <PrintersSection
              path={printerPathSafe}
              setPath={setPrinterPath}
              compareSelection={compareSelection}
              toggleCompareSelect={toggleCompareSelect}
            />
          ) : section === "models" ? (
            <ModelsSection
              path={modelPathSafe}
              setPath={setModelPath}
              compareSelection={compareSelection}
              toggleCompareSelect={toggleCompareSelect}
              sort={modelSort}
              onSortChange={changeModelSort}
            />
          ) : section === "appearance" ? (
            <AppearancePage
              appearance={preview || appearance}
              saved={appearance}
              onChange={changeAppearance}
              onSave={commitAppearance}
              onDiscard={discardAppearance}
              saveState={saveState}
            />
          ) : (
            <StorageSection onSettingsRestored={loadServerConfig} />
          )}
        </div>
      </div>

      <CompareTray
        selection={compareSelection}
        onRemove={removeFromCompare}
        onClear={clearCompare}
        onCompare={() => setDiffModalOpen(true)}
      />

      {diffModalOpen && diffLeft && diffRight && (
        <Modal title="Compare 3MF files" onClose={() => setDiffModalOpen(false)} width={760}>
          <DiffView
            left={diffLeft}
            right={diffRight}
            onClose={() => setDiffModalOpen(false)}
          />
        </Modal>
      )}
    </div>
  );
}

// Last line of defense: if any component throws while rendering, show what
// happened instead of leaving a blank page.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ ...ui, display: "flex", flexDirection: "column", gap: 12, alignItems: "center", justifyContent: "center", height: "100vh", background: c.bg, color: c.amber, padding: 24, textAlign: "center" }}>
        <div>Something went wrong displaying this page.</div>
        <div style={{ ...mono, fontSize: fs(12), color: c.textFaint, maxWidth: 640, wordBreak: "break-word" }}>
          {String(this.state.error?.message || this.state.error)}
        </div>
        <button
          onClick={() => window.location.reload()}
          style={{ ...ui, fontSize: fs(13), background: c.amberDim, color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 4, padding: "7px 14px", cursor: "pointer" }}
        >
          Reload
        </button>
      </div>
    );
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <DataProvider>
        <FarmhandApp />
      </DataProvider>
    </ErrorBoundary>
  );
}
