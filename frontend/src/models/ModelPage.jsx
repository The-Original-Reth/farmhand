import { useEffect, useState } from "react";
import { ChevronRight, Lock, Printer, Upload } from "lucide-react";
import { c, fs, mono, ui, fixed } from "../theme.js";
import { buttonRow, monoText, rowButton, toolButton, uiText } from "../styles.js";
import { renameBundle, renameModel } from "../api.js";
import { useData } from "../data.jsx";

import { BundleCard } from "../bundles/BundleCard.jsx";
import { EditableName } from "../bundles/EditableName.jsx";
import { Upload3mfForm } from "../bundles/Upload3mfForm.jsx";
import { UploadGcodeForm } from "../bundles/UploadGcodeForm.jsx";
import { VersionRow } from "../bundles/VersionRow.jsx";
import { newestFirst, VersionsToggleAll } from "../bundles/versions.jsx";
import { Modal } from "../components/common/dialogs.jsx";
import { Badge, SectionLabel, Thumb } from "../components/common/ui.jsx";
import { AddModelFileForm, DeleteModelButton } from "./modelActions.jsx";
import { nameCollator } from "../lib/order.js";
import { NotesSection } from "../notes/NotesSection.jsx";
import { plural } from "../lib/format.js";

// One model's page: its model file and versions, its notes, and its 3MF files by printer. The open upload dialog and
// which 3MF files are unfolded are kept by ModelsSection.
export function ModelPage({ modelId, setPath, uploadModal, setUploadModal, expansion, compareSelection, toggleCompareSelect }) {
  const { sourceModels, printers, bundlesForModel, versionsByBundle, sourceVersionsByModel, putModel, putBundle } = useData();
  const [sourceOverride, setSourceOverride] = useState(null); // null = the default for its length
  const [addFileOpen, setAddFileOpen] = useState(false);
  const [newVersionOpen, setNewVersionOpen] = useState(false);

  useEffect(() => {
    setSourceOverride(null);
  }, [modelId]);

  const model = sourceModels.find((m) => m.id === modelId);
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", columnGap: 12, flexWrap: "wrap", marginBottom: 10 }}>
          <SectionLabel>Model file</SectionLabel>
          <div style={buttonRow()}>
            {hasFile && (
              <button
                data-testid="stl-new-version"
                onClick={() => setNewVersionOpen(true)}
                title="Upload a newer version of this model file"
                style={rowButton(12, { marginBottom: 10 })}
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
              flexWrap: "wrap", // in a narrow window (a phone) the version count goes under the name rather than off the edge
              columnGap: 12,
              rowGap: 8,
              padding: "12px 16px",
              background: c.panelAlt,
              cursor: sourceRest.length > 0 ? "pointer" : "default",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
              <Thumb src={model.thumb} size={64} background={fixed.preview} placeholderIcon />
              <div style={{ minWidth: 0 }}>
                <div style={uiText(14, c.heading, { overflowWrap: "anywhere" })}>
                  <EditableName value={model.name} label="this model file" extension={{ STL: ".stl", OBJ: ".obj", STEP: ".step" }[model.type] || ".stl"} testId="model-name" textStyle={{ ...ui, fontSize: fs(14) }} onSave={async (name) => putModel(await renameModel(model.id, name))} />
                </div>
                <div style={{ marginTop: 5 }}>
                  <Badge>{model.type}</Badge>
                </div>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginLeft: "auto" }}>
              <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap" })}>
                {plural(sourceList.length, "version")}
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
              <span style={uiText(13, c.textFaint)}>No model file uploaded yet.</span>
              <button
                onClick={() => setAddFileOpen(true)}
                style={toolButton(12)}
              >
                <Upload size={12} />
                Add file
              </button>
            </div>
          )}
        </div>
      </div>

      <NotesSection key={model.id} kind="model" owner={model} />

      <div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", columnGap: 12, flexWrap: "wrap", marginBottom: 10 }}>
          <SectionLabel>3MF files by printer</SectionLabel>
          <div style={buttonRow({ alignItems: "center", rowGap: 0 })}>
            <VersionsToggleAll bundleList={modelBundles} expansion={expansion} />
            <button
              onClick={() => setUploadModal("3mf")}
              style={rowButton(12, { marginBottom: 10 })}
            >
              <Upload size={12} />
              Upload 3MF
            </button>
            <button
              data-testid="upload-gcode"
              onClick={() => setUploadModal("gcode")}
              disabled={modelBundles.length === 0}
              title={modelBundles.length ? "Upload a G-code sliced from one of these 3MF files" : "Upload a 3MF first: a G-code goes with one"}
              style={rowButton(12, { marginBottom: 10, ...(modelBundles.length ? {} : { opacity: 0.55, cursor: "default" }) })}
            >
              <Upload size={12} />
              Upload G-code
            </button>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {modelBundles.map((b) => (
            <BundleCard
              key={b.id}
              bundle={b}
              versions={versionsByBundle[b.id] || []}
              grow
              expansion={expansion}
              compareSelection={compareSelection}
              onToggleCompare={toggleCompareSelect}
              title={
                <>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Printer size={15} color={c.textFaint} />
                    <span style={uiText(14, c.heading)}>{printers.find((p) => p.id === b.printerId).name}</span>
                    <Lock size={12} color={c.textFaint} />
                    <Badge>{b.slicer}</Badge>
                  </div>
                  <div style={monoText(11, c.textFaint, { paddingLeft: 23 })}>
                    <EditableName value={b.name} label="this 3MF file" extension=".3mf" boxed testId="bundle-name" textStyle={{ ...mono, fontSize: fs(12) }} onSave={async (name) => putBundle(await renameBundle(b, name))} />
                  </div>
                </>
              }
            />
          ))}
        </div>
      </div>

      {uploadModal === "3mf" && (
        <Modal title="Upload 3MF" onClose={() => setUploadModal(null)}>
          <Upload3mfForm presetModel={model} onClose={() => setUploadModal(null)} />
        </Modal>
      )}
      {uploadModal === "gcode" && (
        <Modal title="Upload G-code" onClose={() => setUploadModal(null)}>
          <UploadGcodeForm bundles={modelBundles} onClose={() => setUploadModal(null)} />
        </Modal>
      )}
    </div>
  );
}
