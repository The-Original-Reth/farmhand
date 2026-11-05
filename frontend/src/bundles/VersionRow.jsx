import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { monoText, uiText } from "../styles.js";
import { bundle3mfUrl, deleteBundleVersion, deleteSourceModelVersion, sourceModelDownloadUrl } from "../api.js";
import { useData } from "../data.jsx";

import { VersionStar } from "./VersionStar.jsx";
import { subPrinterName } from "../printers/SubPrinters.jsx";
import { CompareSelectButton } from "../compare/CompareTray.jsx";
import { SettingsViewer } from "../compare/SettingsBrowser.jsx";
import { ConfirmDialog, DeleteWarning, Modal } from "../components/common/dialogs.jsx";
import { Badge, DownloadButton, Thumb, TrashButton } from "../components/common/ui.jsx";
import { AddToProjectButton } from "../projects/AddToProject.jsx";

export function VersionRow({ ver, isLatest, showFileStatus, bundle, model, compareSelection = [], onToggleCompare }) {
  const { refresh, printers } = useData();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const subPrinter = showFileStatus && bundle ? subPrinterName(printers, bundle, ver) : null;
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
          : "24px 60px 90px 1fr auto", // a model's newest version also has Add to project
        alignItems: "center",
        padding: "9px 16px",
        borderTop: isLatest ? "none" : `1px solid ${c.border}`,
        gap: 8,
      }}
    >
      {showFileStatus && <Thumb src={ver.thumb} size={36} plateGrid />}
      <div>{isBundleRow && <VersionStar bundle={bundle} ver={ver} />}</div>
      <div style={monoText(13, isLatest ? c.heading : c.textPrimary)}>
        v{ver.v}
      </div>
      <div style={monoText(12, c.textMuted)}>{ver.date}</div>
      <div style={{ minWidth: 0 }}>
        <div style={uiText(13, ver.note ? c.textMuted : c.textFaint)}>
          {ver.note || "—"}
        </div>
        {/* the printer profile (printer preset) it was sliced with */}
        {subPrinter && (
          <div data-testid="version-sub-printer" title="Printer profile: the printer preset it was sliced with" style={monoText(11, c.textFaint, { marginTop: 2, overflowWrap: "anywhere" })}>
            {subPrinter}
          </div>
        )}
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
        {isModelRow && isLatest && <AddToProjectButton model={model} />}
        <DownloadButton
          disabled={showFileStatus && !ver.full}
          href={showFileStatus ? bundle3mfUrl(ver.id) : model ? sourceModelDownloadUrl(model.id, ver.v) : undefined}
        />
        {(isBundleRow || isModelRow) && (
          <TrashButton title="Delete this version" onClick={() => setDeleteOpen(true)} />
        )}
      </div>

      {settingsOpen && bundle && (
        <Modal title="Display Settings" onClose={() => setSettingsOpen(false)} width={960}>
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
