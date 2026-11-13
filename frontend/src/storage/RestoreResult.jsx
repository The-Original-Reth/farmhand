import { c, fs, ui } from "../theme.js";
import { whatsIn } from "../lib/format.js";

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
      {result.broughtIn && <BroughtIn b={result.broughtIn} list={list} />}
      {result.warnings.map((w) => (
        <div key={w} style={{ color: c.amber }}>{w}</div>
      ))}
    </div>
  );
}

// The files another Farmhand keeps in the shared folders that Farmhand didn't have, brought in (none copied)
function BroughtIn({ b, list }) {
  const added = b.projects.filter((p) => p.added);
  const fresh = b.projects.filter((p) => !p.added);
  if (!b.models.length && !b.threemfs.length && !b.projects.length) return <div>No files to bring in: Farmhand already has every one.</div>;
  return (
    <>
      {b.models.length > 0 && <div data-testid="brought-models">Models brought in: {list(b.models)}.</div>}
      {b.threemfs.length > 0 && <div data-testid="brought-threemfs">3MF files brought in: {list(b.threemfs)}.</div>}
      {fresh.length > 0 && <div data-testid="brought-projects">Projects brought in: {list(fresh.map((p) => p.name))}.</div>}
      {added.map((p) => (
        <div key={p.name} data-testid="brought-added">
          Added to the project {p.name}: {whatsIn(p.files)}.
        </div>
      ))}
    </>
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
