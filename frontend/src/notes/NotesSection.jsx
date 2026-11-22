import { useLayoutEffect, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { toneColor, toolButton, uiText } from "../styles.js";

import { readStoredObject, writeStored } from "../lib/storage.js";
import { NOTE_KINDS } from "./noteKinds.js";
import { fmtWhen } from "../lib/format.js";
import { useNoteDraft } from "./useNoteDraft.js";

const NOTES_MAX = 20000;

// Whether a model's, printer's or 3MF's notes are folded down to their first line. Every one STARTS folded; opening
// or closing one is remembered for that model/printer/3MF, in this browser. Anything unreadable means folded.
// (The keys changed when folding went from two lines to one, so notes left open before that start folded again.)
const notesCollapsedKey = (kind) => NOTE_KINDS[kind].storage.collapsed;
function readNotesCollapsed(kind, id) {
  const choice = readStoredObject(notesCollapsedKey(kind))[id];
  return typeof choice === "boolean" ? choice : true;
}
function writeNotesCollapsed(kind, id, collapsed) {
  writeStored(notesCollapsedKey(kind), { ...readStoredObject(notesCollapsedKey(kind)), [id]: collapsed });
}

// Free-text notes about a model, a printer, a 3MF or a printer's 1500-hour service (`kind`, see NOTE_KINDS) — `owner`
// is the thing they're about. Typed text is protected three ways: it's kept as a draft in this browser if you leave
// or reload, the browser asks before a tab with unsaved notes is closed, and a save that would overwrite what
// someone else saved meanwhile is stopped. One component serves every kind, so they all behave identically.
export function NotesSection({ kind, owner }) {
  const k = NOTE_KINDS[kind];
  const ownerId = owner.id;
  const description = k.description(owner);
  const placeholder = k.placeholder;
  const { text, setText, phase, setPhase, conflict, dirty, busy, status, save, discard, useTheirs } = useNoteDraft(kind, owner);
  const areaRef = useRef(null);
  const [collapsed, setCollapsedState] = useState(() => readNotesCollapsed(kind, ownerId));
  const focusOnExpand = useRef(false);
  const setCollapsed = (next) => {
    setCollapsedState(next);
    writeNotesCollapsed(kind, ownerId, next);
  };
  const bodyId = `notes-body-${kind}-${ownerId}`;

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

        {conflict && <NotesConflict conflict={conflict} useTheirs={useTheirs} save={save} busy={busy} button={button} />}

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 12, flexWrap: "wrap" }}>
          <div
            data-testid="notes-status"
            style={{ ...ui, fontSize: fs(12), lineHeight: 1.5, flex: 1, minWidth: 200, color: toneColor(status.tone) }}
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

// Someone else saved the notes while they were being edited: their version, and which to keep
function NotesConflict({ conflict, useTheirs, save, busy, button }) {
  return (
    <div data-testid="notes-conflict" style={{ marginTop: 12, border: `1px solid ${c.amber}`, borderRadius: 4, padding: 12, background: c.panelAlt }}>
      <div style={uiText(13, c.heading, { marginBottom: 4 })}>Someone else saved these notes while you were editing.</div>
      <div style={uiText(12, c.textMuted, { lineHeight: 1.6, marginBottom: 8 })}>
        Nothing was overwritten. Their version{conflict.updatedAt ? ` (saved ${fmtWhen(conflict.updatedAt, "")})` : ""} is below, and yours is still in the box above.
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
  );
}
