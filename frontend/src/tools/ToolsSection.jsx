import { useRef, useState } from "react";
import { ExternalLink, GripVertical, Pencil, Plus } from "lucide-react";
import { c } from "../theme.js";
import { errorText } from "../api.js";
import { cancelButton, fieldBox, headerButton, monoText, panelBox, primaryButton, uiText } from "../styles.js";
import { TrashButton } from "../components/common/ui.jsx";

// An address as typed, made into one the browser can open: "klipper3d.org" gets https:// in front
const fullAddress = (typed) => {
  const t = typed.trim();
  return !t || /^[a-z][a-z0-9+.-]*:/i.test(t) ? t : `https://${t}`;
};
// Why a website can't be saved as typed, or null when it can
const linkProblem = (link) => {
  const url = fullAddress(link.url);
  if (!url) return "Give this website an address.";
  if (!/^https?:\/\/[^\s/]+/i.test(url)) return "Only web addresses (http:// or https://) can be added.";
  if (url.length > 2000) return "That address is too long.";
  if (link.name.trim().length > 100) return "Keep the name to 100 characters.";
  return null;
};

// The Tools page: a list of websites, each opening in a new tab. Add puts a new one at the end; each line has Edit
// (change its name or address there) and Delete at its end, and is moved by dragging its handle. Every change is sent
// to the server straight away as the whole list (onSave resolves once the server has it). A website without a name
// is shown by its address.
export function ToolsSection({ links = [], onSave }) {
  const [editing, setEditing] = useState(null); // the line being edited: its place, or "new" for Add (null = none)
  const [form, setForm] = useState({ name: "", url: "" }); // what's typed for it
  const [tried, setTried] = useState(false); // Save was pressed: show what's wrong with it
  const [removing, setRemoving] = useState(null); // the place of the line asking "Delete?"
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null); // the last change the server didn't take
  const [dragging, setDragging] = useState(null); // the place of the line being dragged
  const [over, setOver] = useState(null); // the place it would be dropped into
  const [shown, setShown] = useState(null); // the list as changed here while the server is still saving it (null = as saved)
  const queue = useRef(Promise.resolve()); // the saves not answered yet, one after another
  const waiting = useRef(0); // how many of them
  const current = shown || links; // every change starts from what's on the screen, saved or not

  // A change shows at once and is sent after any still on their way, so the next one can be made straight away (the
  // server answers only once it has also written the settings copy, which can take a while on a small computer or a
  // NAS). Resolves true once the server has it; when it doesn't take one, the list goes back to what it last took.
  const send = (next) => {
    setShown(next);
    setError(null);
    waiting.current += 1;
    const saved = queue.current.then(() => onSave(next)).then(
      () => true,
      (e) => {
        setError(errorText(e));
        return false;
      },
    );
    queue.current = saved;
    saved.then(() => {
      waiting.current -= 1;
      if (waiting.current === 0) setShown(null);
    });
    return saved;
  };
  // the Add, Save and Delete buttons wait for their own answer, to close the form or keep it open with the message
  const sendAndWait = async (next) => {
    setBusy(true);
    const ok = await send(next);
    setBusy(false);
    return ok;
  };
  const open = (which) => {
    setEditing(which);
    setForm(which === "new" ? { name: "", url: "" } : { ...current[which] });
    setTried(false);
    setRemoving(null);
    setError(null);
  };
  const saveForm = async () => {
    setTried(true);
    if (linkProblem(form)) return;
    const link = { name: form.name.trim(), url: fullAddress(form.url) };
    const next = editing === "new" ? [...current, link] : current.map((l, i) => (i === editing ? link : l));
    if (await sendAndWait(next)) setEditing(null);
  };
  const remove = async (i) => {
    if (await sendAndWait(current.filter((_, j) => j !== i))) setRemoving(null);
  };
  // Dragging follows the pointer itself (mouse, pen or finger) rather than the browser's drag-and-drop, which
  // touch screens don't do: the line under the pointer is where the dragged one goes when it's let go.
  const lineAt = (x, y) => {
    const el = document.elementFromPoint(x, y)?.closest("[data-link-line]");
    return el ? Number(el.dataset.linkLine) : null;
  };
  const startDrag = (e, i) => {
    if (e.button > 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(i);
    setOver(i);
  };
  const followDrag = (e) => {
    if (dragging === null) return;
    const at = lineAt(e.clientX, e.clientY);
    if (at !== null) setOver(at);
  };
  const endDrag = () => {
    const from = dragging;
    const to = over;
    setDragging(null);
    setOver(null);
    if (from === null || to === null || from === to) return;
    const next = [...current];
    next.splice(to, 0, next.splice(from, 1)[0]);
    send(next);
  };

  const problem = tried ? linkProblem(form) : null;
  const formRow = (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <input
          autoFocus
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          onKeyDown={(e) => e.key === "Enter" && saveForm()}
          placeholder="Name (optional)"
          aria-label="Website name"
          style={{ ...fieldBox(), padding: "6px 8px", flex: "1 1 160px", minWidth: 0 }}
        />
        <input
          value={form.url}
          onChange={(e) => setForm({ ...form, url: e.target.value })}
          onKeyDown={(e) => e.key === "Enter" && saveForm()}
          placeholder="Address, e.g. https://www.klipper3d.org"
          aria-label="Website address"
          style={{ ...fieldBox(), padding: "6px 8px", flex: "2 1 240px", minWidth: 0, borderColor: problem ? c.danger : c.border }}
        />
      </div>
      {problem && <div style={uiText(12, c.danger)}>{problem}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={saveForm} disabled={busy} style={primaryButton(busy)}>{busy ? "Saving…" : editing === "new" ? "Add" : "Save"}</button>
        <button onClick={() => setEditing(null)} disabled={busy} style={cancelButton(busy)}>Cancel</button>
      </div>
    </div>
  );

  return (
    <div data-testid="tools-section" style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 760 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div style={uiText(15, c.heading, { fontWeight: 600 })}>Websites</div>
        <button onClick={() => open("new")} disabled={editing === "new"} style={headerButton()}>
          <Plus size={12} /> Add
        </button>
      </div>
      {error && <div style={uiText(12, c.danger)}>Not saved: {error}</div>}

      {current.length === 0 && editing !== "new" ? (
        <div style={panelBox({ padding: 20 })}>
          <div style={uiText(13, c.textFaint)}>No websites yet. Press Add to put in the ones you use around the farm.</div>
        </div>
      ) : (
        <div style={panelBox()}>
          {current.map((link, i) => {
            const line = { borderTop: i ? `1px solid ${c.border}` : "none" };
            if (editing === i) return <div key={i} style={line}>{formRow}</div>;
            const dropHere = over === i && dragging !== null && dragging !== i;
            return (
              <div
                key={i}
                data-link-line={i}
                style={{
                  ...line, display: "flex", alignItems: "center", gap: 8, padding: "8px 14px 8px 8px",
                  opacity: dragging === i ? 0.4 : 1, boxShadow: dropHere ? `inset 0 0 0 2px ${c.amber}` : "none",
                }}
              >
                <span
                  onPointerDown={(e) => startDrag(e, i)}
                  onPointerMove={followDrag}
                  onPointerUp={endDrag}
                  onPointerCancel={() => {
                    setDragging(null);
                    setOver(null);
                  }}
                  title="Drag to move"
                  aria-label="Drag to move"
                  style={{
                    display: "flex", alignItems: "center", alignSelf: "stretch", padding: "0 4px", color: dragging === i ? c.amber : c.textFaint,
                    cursor: dragging === i ? "grabbing" : "grab", flexShrink: 0, touchAction: "none", userSelect: "none",
                  }}
                >
                  <GripVertical size={16} />
                </span>
                <a
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none", flex: 1, minWidth: 0, padding: "2px 0" }}
                >
                  <ExternalLink size={14} color={c.amber} style={{ flexShrink: 0 }} />
                  <div style={{ minWidth: 0 }}>
                    <div style={uiText(14, c.textPrimary, { overflowWrap: "anywhere" })}>{link.name || link.url}</div>
                    {link.name && <div style={monoText(12, c.textFaint, { overflowWrap: "anywhere" })}>{link.url}</div>}
                  </div>
                </a>
                {removing === i ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                    <span style={uiText(12, c.textMuted)}>Delete?</span>
                    <button onClick={() => remove(i)} disabled={busy} style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}>
                      Delete
                    </button>
                    <button onClick={() => setRemoving(null)} disabled={busy} style={headerButton()}>Keep</button>
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                    <button onClick={() => open(i)} title="Edit this website" aria-label="Edit this website" style={headerButton()}>
                      <Pencil size={12} /> Edit
                    </button>
                    <TrashButton onClick={() => setRemoving(i)} title="Delete this website" />
                  </div>
                )}
              </div>
            );
          })}
          {editing === "new" && <div style={{ borderTop: current.length ? `1px solid ${c.border}` : "none" }}>{formRow}</div>}
        </div>
      )}
    </div>
  );
}
