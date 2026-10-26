import { useEffect, useState } from "react";
import { c, fs, mono, ui } from "../theme.js";
import { cancelButton, monoText, uiText } from "../styles.js";
import { importScannedFiles, scanStlFolder } from "../api.js";
import { useData } from "../data.jsx";

import { Badge } from "../components/common/ui.jsx";
import { formatBytes } from "../lib/format.js";

const SCAN_BATCH = 10; // files added per request, so a big import shows progress and one slow batch can't time out the lot

export function ScanStlDialog({ onClose }) {
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
      style={cancelButton()}
    >
      {label}
    </button>
  );

  if (phase === "scanning") {
    return <div style={uiText(13, c.textFaint)}>Looking through the STL folder…</div>;
  }
  if (phase === "error") {
    return (
      <>
        <div style={uiText(13, c.amber, { lineHeight: 1.6, marginBottom: 14 })}>{error}</div>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>{closeBtn()}</div>
      </>
    );
  }
  if (phase === "adding") {
    const pct = chosen.length ? Math.round((progress / chosen.length) * 100) : 0;
    return (
      <div data-testid="scan-progress">
        <div style={uiText(13, c.textMuted, { marginBottom: 10 })}>
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
        <div style={uiText(14, c.heading, { marginBottom: 8 })}>
          Moved {plural(summary.added, "file", "files")} into the library.
        </div>
        {summary.added > 0 && (
          <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 8 })}>
            They're now filed in Farmhand's own folders. The folders they came from were left as they were.
          </div>
        )}
        {summary.stopped && (
          <div style={uiText(12, c.amber, { lineHeight: 1.6, marginBottom: 8 })}>
            It stopped early: {summary.stopped} What was moved so far is kept — scan again to continue.
          </div>
        )}
        {summary.failed.length > 0 && (
          <div style={uiText(12, c.amber, { lineHeight: 1.6, marginBottom: 8 })}>
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
        <div data-testid="scan-none" style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 14 })}>
          No new files found in <span style={mono}>{scan.root}</span>. Everything there is already in the library.
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>{closeBtn()}</div>
      </>
    );
  }
  return (
    <div data-testid="scan-results">
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 10 })}>
        Found <b style={{ color: c.heading }}>{plural(files.length, "new file", "new files")}</b>
        {scan.truncated ? " (that's the first batch — add these, then scan again for more)" : ""} in{" "}
        <span style={mono}>{scan.root}</span>.
      </div>
      <div data-testid="scan-move-note" style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
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
              <div style={uiText(13, c.heading, { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>{f.name}</div>
              <div style={monoText(11, c.textFaint, { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>
                {f.folder || "top level"}
              </div>
            </div>
            {f.nameInLibrary && <Badge tone="amber">name already in library</Badge>}
            <Badge>{f.fileType}</Badge>
            <span style={monoText(11, c.textFaint, { width: 58, textAlign: "right", flexShrink: 0 })}>{formatBytes(f.sizeBytes)}</span>
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
