import { createContext, useContext, useMemo, useState } from "react";
import { Send } from "lucide-react";
import { c } from "../theme.js";
import { toolButton, uiText } from "../styles.js";
import { Modal, ModalActions } from "../components/common/dialogs.jsx";
import { SearchBox } from "../components/common/fields.jsx";

// "Send to <plugin>": files from Farmhand opened in a plugin that takes them (a slicer: its manifest's send_files,
// docs/plugins.md). Sending opens the plugin's page at its send_files path with the files' refs in the address
// (?file=model:12&file=3mf:40), and the plugin reads them through the plugin API (library:read).
//
// A ref names one file: model:<id> (its newest version), 3mf:<version id>, project-stl:<project>:<file>,
// project-3mf:<project>:<file>.

// { senders: [{ id, name, label, kinds }], send(id, refs) }: the plugins files can be sent to, and sending them
export const SendFilesContext = createContext({ senders: [], send: () => {} });
export const useSendFiles = () => useContext(SendFilesContext);

// What kind of file a model is (its type: STL, OBJ, STEP), as send_files' kinds say it; null for one no plugin takes
export const modelKind = (model) => {
  const kind = (model.type || "").toLowerCase();
  return ["stl", "obj"].includes(kind) ? kind : null;
};

// What kind of file a name is, as send_files' kinds say it ("stl", "obj", "3mf"; null for one no plugin takes)
export const sendKind = (name) => {
  const ext = (name || "").toLowerCase().match(/\.([a-z0-9]+)$/)?.[1];
  return ["stl", "obj", "3mf"].includes(ext) ? ext : null;
};

// The address a plugin's page opens at for these files: its send_files path, with a file= for each ref
export const sendPath = (path, refs) =>
  `${path}${path.includes("?") ? "&" : "?"}${refs.map((r) => `file=${encodeURIComponent(r)}`).join("&")}`;

// One file, sent straight away: a "Send to <label>" button for each plugin that takes its kind
export function SendButton({ fileRef, kind, size = 12, style, testId }) {
  const { senders, send } = useSendFiles();
  const takers = senders.filter((s) => kind && s.kinds.includes(kind));
  return takers.map((s) => (
    <button
      key={s.id}
      data-testid={testId}
      onClick={(e) => {
        e.stopPropagation();
        send(s.id, [fileRef]);
      }}
      title={`Open it in ${s.name}`}
      style={toolButton(size, { whiteSpace: "nowrap", flexShrink: 0, ...style })}
    >
      <Send size={size} />
      Send to {s.label}
    </button>
  ));
}

// Several files to choose from (a project's, or every model): a "Send to <label>…" button for each plugin that
// takes any of them, which asks which ones. candidates: [{ fileRef, name, kind, group }]
export function SendSeveralButton({ candidates, size = 12, style, testId }) {
  const { senders, send } = useSendFiles();
  const [open, setOpen] = useState(null); // the plugin choosing for
  const takers = senders.filter((s) => candidates.some((f) => s.kinds.includes(f.kind)));
  return (
    <>
      {takers.map((s) => (
        <button key={s.id} data-testid={testId} onClick={() => setOpen(s)} title={`Choose files to open in ${s.name}`} style={toolButton(size, { whiteSpace: "nowrap", flexShrink: 0, ...style })}>
          <Send size={size} />
          Send to {s.label}…
        </button>
      ))}
      {open && (
        <ChooseFiles
          sender={open}
          candidates={candidates.filter((f) => open.kinds.includes(f.kind))}
          onClose={() => setOpen(null)}
          onSend={(refs) => {
            setOpen(null);
            send(open.id, refs);
          }}
        />
      )}
    </>
  );
}

function ChooseFiles({ sender, candidates, onClose, onSend }) {
  const [picked, setPicked] = useState([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return candidates.filter((f) => words.every((w) => `${f.name} ${f.group || ""}`.toLowerCase().includes(w)));
  }, [candidates, query]);
  const groups = [...new Set(shown.map((f) => f.group || ""))];
  const toggle = (ref) => setPicked((p) => (p.includes(ref) ? p.filter((r) => r !== ref) : [...p, ref]));
  return (
    <Modal title={`Send to ${sender.label}`} onClose={onClose} width={520}>
      <div style={uiText(12, c.textMuted, { marginBottom: 10, lineHeight: 1.5 })}>
        Tick the files to open in {sender.name}. An STL is sliced for the printer you pick there; a 3MF brings its own.
      </div>
      {candidates.length > 8 && <SearchBox value={query} onChange={setQuery} placeholder="Find a file" style={{ marginBottom: 10 }} />}
      <div style={{ maxHeight: 360, overflow: "auto", marginBottom: 12, border: `1px solid ${c.border}`, borderRadius: 6 }}>
        {shown.length === 0 && <div style={uiText(13, c.textFaint, { padding: 12 })}>No file matches.</div>}
        {groups.map((g) => (
          <div key={g}>
            {g && <div style={uiText(11, c.textFaint, { padding: "8px 12px 2px", textTransform: "uppercase", letterSpacing: 0.5 })}>{g}</div>}
            {shown.filter((f) => (f.group || "") === g).map((f) => (
              <label key={f.fileRef} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", cursor: "pointer" }}>
                <input type="checkbox" checked={picked.includes(f.fileRef)} onChange={() => toggle(f.fileRef)} />
                <span style={uiText(13, c.textPrimary, { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>{f.name}</span>
              </label>
            ))}
          </div>
        ))}
      </div>
      <ModalActions
        onClose={onClose}
        onSubmit={() => (picked.length ? onSend(picked) : setError("Tick at least one file to send."))}
        actionLabel={picked.length > 1 ? `Send ${picked.length} files` : "Send"}
        submitting={false}
        errorMsg={error}
      />
    </Modal>
  );
}

// The files of a project a plugin may be sent: its own STLs and 3MFs, and the models and 3MFs it uses from Models
export function projectCandidates(project, sourceModels, bundles) {
  const own = (files, key, group) =>
    files
      .filter((f) => sendKind(f.versions[0]?.filename || f.name))
      .map((f) => ({ fileRef: `project-${key}:${project.id}:${f.id}`, name: f.name, kind: sendKind(f.versions[0]?.filename || f.name), group }));
  const models = project.modelIds
    .map((id) => sourceModels.find((m) => m.id === id))
    .filter((m) => m && m.versions.length && modelKind(m))
    .map((m) => ({ fileRef: `model:${m.id}`, name: m.name, kind: modelKind(m), group: "Models it uses" }));
  const threemfs = project.bundleIds
    .map((id) => bundles.find((b) => b.id === id))
    .filter((b) => b && b.versions[0]?.full)
    .map((b) => ({ fileRef: `3mf:${b.versions[0].id}`, name: b.name, kind: "3mf", group: "3MFs it uses" }));
  return [...own(project.stlFiles, "stl", "Its STLs"), ...own(project.threemfFiles, "3mf", "Its 3MFs"), ...models, ...threemfs];
}

// Every model in Models with a file a plugin may be sent
export const modelCandidates = (sourceModels) =>
  sourceModels
    .filter((m) => m.versions.length && modelKind(m))
    .map((m) => ({ fileRef: `model:${m.id}`, name: m.name, kind: modelKind(m) }))
    .sort((a, b) => a.name.localeCompare(b.name));
