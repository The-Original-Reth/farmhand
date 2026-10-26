import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, ChevronRight, Lock, Printer, Search, Upload, X } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { linkButton, monoText, toolButton, uiText } from "../styles.js";
import { renameBundleVersion, renameModel } from "../api.js";
import { useData } from "../data.jsx";

import { BundleCard } from "../bundles/BundleCard.jsx";
import { EditableName } from "../bundles/EditableName.jsx";
import { Upload3mfForm } from "../bundles/Upload3mfForm.jsx";
import { VersionRow } from "../bundles/VersionRow.jsx";
import { newestFirst, useBundleExpansion, VersionsToggleAll } from "../bundles/versions.jsx";
import { Modal } from "../components/common/dialogs.jsx";
import { Badge, SectionLabel, Thumb } from "../components/common/ui.jsx";
import { useMediaQuery } from "../hooks/useMediaQuery.js";
import { matchModel, searchableExtras, searchWords } from "../lib/search.jsx";
import { ModelListRow } from "./ModelListRow.jsx";
import { RedrawPreviewsDialog } from "./RedrawPreviewsDialog.jsx";
import { ScanStlDialog } from "./ScanStlDialog.jsx";
import { UploadStlForm } from "./UploadStlForm.jsx";
import { AddModelFileForm, DeleteModelButton } from "./modelActions.jsx";
import { MODEL_SORTS, nameCollator, sortModelRows } from "./modelSort.js";
import { NotesSection } from "../notes/NotesSection.jsx";

function UploadBar({ onUploadStl, onUploadBundle, onScan, bundleLabel = "Upload 3MF" }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {onScan && (
        <button
          onClick={onScan}
          title="Look through the STL folder for files that were added from outside Farmhand"
          style={toolButton(13)}
        >
          <Search size={13} />
          Scan STL folder
        </button>
      )}
      <button
        onClick={onUploadStl}
        style={toolButton(13)}
      >
        <Upload size={13} />
        Upload STL
      </button>
      <button
        onClick={onUploadBundle}
        style={toolButton(13)}
      >
        <Upload size={13} />
        {bundleLabel}
      </button>
    </div>
  );
}

export function ModelsSection({ path, setPath, compareSelection, toggleCompareSelect, sort, onSortChange }) {
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
            <span style={uiText(12, c.textFaint)}>Sort by</span>
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
            <span data-testid="model-count" style={uiText(12, c.textFaint, { marginLeft: 6 })}>
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
          <div data-testid="model-search-empty" style={uiText(13, c.textMuted, { padding: "24px 4px", lineHeight: 1.7 })}>
            No models match <b style={{ color: c.heading }}>“{query.trim()}”</b>. Every word has to match the name, a 3MF file, a printer, the slicer or the notes.{" "}
            <button
              data-testid="model-search-empty-clear"
              onClick={() => setQuery("")}
              style={linkButton()}
            >
              Clear search
            </button>
          </div>
        ) : sorted.length === 0 ? (
          <div style={uiText(13, c.textFaint, { padding: "24px 4px" })}>
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
                style={toolButton(12, { marginBottom: 10 })}
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
                <div style={uiText(14, c.heading)}>
                  <EditableName value={model.name} label="this model file" extension={{ STL: ".stl", OBJ: ".obj", STEP: ".step" }[model.type] || ".stl"} testId="model-name" textStyle={{ ...ui, fontSize: fs(14) }} onSave={(name) => renameModel(model.id, name)} />
                </div>
                <div style={{ marginTop: 5 }}>
                  <Badge>{model.type}</Badge>
                </div>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={uiText(12, c.textFaint)}>
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <SectionLabel>3MF files by printer</SectionLabel>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <VersionsToggleAll bundleList={modelBundles} expansion={expansion} />
            <button
              onClick={() => setUploadModal("3mf")}
              style={toolButton(12, { marginBottom: 10 })}
            >
              <Upload size={12} />
              Upload 3MF
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
                    <EditableName value={b.name} label="this 3MF file" extension=".3mf" boxed testId="bundle-name" textStyle={{ ...mono, fontSize: fs(12) }} onSave={(name) => renameBundleVersion(b.versions[0].id, name)} />
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
    </div>
  );
}
