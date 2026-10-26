import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { errorText } from "../api.js";
import { toolButton, uiText } from "../styles.js";
import { useData } from "../data.jsx";

import { NOTE_KINDS } from "./noteKinds.js";

const NOTES_MAX = 20000;
const draftKey = (kind, id) => `${NOTE_KINDS[kind].storage.draft}.${id}`;
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
const notesCollapsedKey = (kind) => NOTE_KINDS[kind].storage.collapsed;
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

// Free-text notes about a model, a printer, a 3MF or a printer's 1500-hour service (`kind`, see NOTE_KINDS) — `owner`
// is the thing they're about. Typed text is protected three ways: it's kept as a draft in this browser if you leave
// or reload, the browser asks before a tab with unsaved notes is closed, and a save that would overwrite what
// someone else saved meanwhile is stopped. One component serves every kind, so they all behave identically.
export function NotesSection({ kind, owner }) {
  const { refresh } = useData();
  const k = NOTE_KINDS[kind];
  const ownerId = owner.id;
  const { saved, rev, updatedAt } = k.read(owner);
  const onSave = ({ notes, baseRevision }) => k.save(ownerId, notes, baseRevision);
  const description = k.description(owner);
  const placeholder = k.placeholder;

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
        setError(errorText(e));
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
        <div style={uiText(13, c.textFaint)}>Notes</div>
        {!collapsed && (
          <span style={uiText(12, c.textFaint)}>
            {description}
          </span>
        )}
        <button
          data-testid="notes-toggle"
          aria-expanded={!collapsed}
          aria-controls={bodyId}
          onClick={() => setCollapsed(!collapsed)}
          style={toolButton(12, { marginLeft: "auto" })}
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
            <div style={uiText(13, c.heading, { marginBottom: 4 })}>Someone else saved these notes while you were editing.</div>
            <div style={uiText(12, c.textMuted, { lineHeight: 1.6, marginBottom: 8 })}>
              Nothing was overwritten. Their version{conflict.updatedAt ? ` (saved ${when(conflict.updatedAt)})` : ""} is below, and yours is still in the box above.
            </div>
            <pre
              data-testid="notes-theirs"
              style={uiText(13, c.textPrimary, { background: c.panel, border: `1px solid ${c.border}`, borderRadius: 3, padding: "8px 10px", margin: "0 0 10px", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 180, overflow: "auto" })}
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
