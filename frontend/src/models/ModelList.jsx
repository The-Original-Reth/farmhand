import { useDeferredValue, useEffect, useMemo, useRef } from "react";
import { ArrowDown, ArrowUp, Search, Upload } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { fieldBox, linkButton, toolButton, uiText } from "../styles.js";
import { useData } from "../data.jsx";

import { Upload3mfForm } from "../bundles/Upload3mfForm.jsx";
import { UploadGcodeForm } from "../bundles/UploadGcodeForm.jsx";
import { Modal } from "../components/common/dialogs.jsx";
import { SearchBox } from "../components/common/fields.jsx";
import { useMediaQuery } from "../hooks/useMediaQuery.js";
import { matchModel, searchWords } from "../lib/search.jsx";
import { ModelListRow } from "./ModelListRow.jsx";
import { RedrawPreviewsDialog } from "./RedrawPreviewsDialog.jsx";
import { ScanStlDialog } from "./ScanStlDialog.jsx";
import { UploadStlForm } from "./UploadStlForm.jsx";
import { MODEL_SORTS, sortModelRows } from "./modelSort.js";

// The Models page's list: the search, the sort, every model as a row, and the upload and scan dialogs. The search
// and the open dialog are kept by ModelsSection, so they're still there after opening a model and coming back.
function UploadBar({ onUploadStl, onUploadBundle, onUploadGcode, onScan, bundleLabel = "Upload 3MF" }) {
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
      <button
        data-testid="upload-gcode"
        onClick={onUploadGcode}
        disabled={!onUploadGcode}
        title={onUploadGcode ? "Upload a G-code sliced from one of the 3MF files" : "Upload a 3MF first: a G-code goes with one"}
        style={toolButton(13, onUploadGcode ? undefined : { opacity: 0.55, cursor: "default" })}
      >
        <Upload size={13} />
        Upload G-code
      </button>
    </div>
  );
}

export function ModelList({ query, setQuery, uploadModal, setUploadModal, sort, onSortChange, setPath }) {
  const { sourceModels, bundles, bundlesForModel, searchIndex } = useData();
  const narrow = useMediaQuery("(max-width: 760px)"); // two columns, or one on a narrow screen
  const searchRef = useRef(null);

  // "/" jumps to the search box (unless you're already typing somewhere)
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || uploadModal) return;
      const tag = e.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target?.isContentEditable) return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [uploadModal]);

  // The list: each model with its counts (once per load), then those matching the search, sorted (once per search,
  // sort or load). The search follows the typing a moment behind, so typing stays quick on a big library.
  const rows = useMemo(
    () =>
      sourceModels.map((m) => {
        const mBundles = bundlesForModel(m.id);
        return { m, bundleCount: mBundles.length, printerCount: new Set(mBundles.map((bundle) => bundle.printerId)).size };
      }),
    [sourceModels, bundlesForModel],
  );
  const searched = useDeferredValue(query);
  const words = useMemo(() => searchWords(searched), [searched]);
  const sorted = useMemo(() => {
    const matched = [];
    rows.forEach((row) => {
      const hit = matchModel(row.m, words, words.length ? searchIndex.get(row.m.id) || [] : []);
      if (hit) matched.push({ ...row, reasons: hit.reasons });
    });
    return sortModelRows(matched, sort);
  }, [rows, words, searchIndex, sort]);

  const searching = words.length > 0;
  const columns = narrow ? 1 : 2;
  const lastRow = Math.floor((sorted.length - 1) / columns);
  const chooseSort = onSortChange; // kept with the other settings, so every browser shows the same order
  const control = fieldBox();

  return (
    <div>
      <SearchBox
        value={query}
        onChange={setQuery}
        inputRef={searchRef}
        testId="model-search"
        clearTestId="model-search-clear"
        placeholder="Search models, 3MF files, printers or notes…   ( / )"
        label="Search models"
        style={{ maxWidth: 460, marginBottom: 12 }}
      />

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
            {/* and every 3MF in the library: "39 models / 79 3MF" */} / {bundles.length} 3MF
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
          onUploadGcode={bundles.length ? () => setUploadModal("gcode") : null}
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
      {uploadModal === "gcode" && (
        <Modal title="Upload G-code" onClose={() => setUploadModal(null)}>
          <UploadGcodeForm bundles={bundles} onClose={() => setUploadModal(null)} />
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
