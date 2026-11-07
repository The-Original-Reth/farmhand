import { HardDrive } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { monoText, panelBox, uiText } from "../styles.js";

import { Badge } from "../components/common/ui.jsx";
import { fmtWhen } from "../lib/format.js";

// Why a chosen folder can't be used right now (null when it can): the words on its card's badge
export const locationProblem = (status) =>
  !status.exists ? "Folder not found" : !status.writable ? "Not writable" : !status.markerOk ? "Marker missing — the share may be unmounted" : null;

// Where Farmhand's settings are kept on the network (the server also keeps them itself), under Settings' Advanced:
// choosing another folder, or none. (Save all and Load all settings are on the Save location card.)
export function ConfigLocationCard({ info, onChoose, onClear, error }) {
  const btn = { ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.borderStrong}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" };
  const set = info?.isSet;
  const status = info?.status;
  const problem = set ? locationProblem(status) : null;
  const lastError = info?.lastWrite && info.lastWrite.ok === false ? info.lastWrite.error : null;

  return (
    <div data-testid="config-card" style={panelBox({ padding: 16 })}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div style={uiText(15, c.heading)}>Settings folder</div>
        <div style={{ display: "flex", gap: 6 }}>
          <Badge tone={set ? "teal" : "muted"}>{set ? "network folder" : "server only"}</Badge>
          {set && (problem ? <Badge tone="amber">{problem}</Badge> : <Badge tone="green">ready</Badge>)}
        </div>
      </div>
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
        Where Save all writes every setting, and a copy after every change; the save location's farmhand-configs folder
        unless another is chosen here.
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", border: `1px solid ${c.border}`, borderRadius: 4, background: c.panelAlt, marginBottom: 10 }}>
        <HardDrive size={15} color={c.textFaint} />
        <span data-testid="config-path" style={monoText(12, set ? c.heading : c.textFaint, { wordBreak: "break-all" })}>
          {set ? info.path : "No network folder chosen — settings are kept on the server only"}
        </span>
      </div>

      {set && (
        <div data-testid="config-file" style={uiText(12, c.textFaint, { marginBottom: 10 })}>
          {info.file?.exists ? (
            <>
              <span style={mono}>farmhand-config.json</span> — last written {fmtWhen(info.file.modifiedAt, null)}. Next to it, a file per
              printer in <span style={mono}>printers/</span> and per model in <span style={mono}>models/</span>.
            </>
          ) : (
            <>No settings file in this folder yet.</>
          )}
        </div>
      )}
      {lastError && (
        <div data-testid="config-error" style={uiText(12, c.amber, { lineHeight: 1.5, marginBottom: 10 })}>
          The last copy couldn't be written: {lastError} Your settings are still safe on the server.
        </div>
      )}
      {error && <div style={uiText(12, c.amber, { lineHeight: 1.5, marginBottom: 10 })}>{error}</div>}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button data-testid="config-choose" onClick={onChoose} style={btn}>
          {set ? "Change folder…" : "Choose folder…"}
        </button>
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
export function RestoreResult({ result }) {
  const list = (names) => names.join(", ");
  return (
    <div data-testid="config-restore-result" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 14, ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.7 }}>
      <div style={{ color: c.heading, marginBottom: 4 }}>Loaded: {list(result.restored)}.</div>
      {result.sharesAdded.length > 0 && <div>Network shares added: {list(result.sharesAdded)}. They connect in the background.</div>}
      {result.sharesKept.length > 0 && <div>Already here, kept as they were: {list(result.sharesKept)}.</div>}
      {result.needsPassword.length > 0 && (
        <div style={{ color: c.amber }}>
          Needs its password (a share's password is never saved in the settings): {list(result.needsPassword)}. Use Edit on the share.
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
