import { useEffect, useRef, useState } from "react";
import { errorText } from "../api.js";
import { useData } from "../data.jsx";
import { readStored, writeStored } from "../lib/storage.js";
import { NOTE_KINDS } from "./noteKinds.js";
import { fmtWhen } from "../lib/format.js";

// A draft of the notes, kept in this browser until they're saved
const draftKey = (kind, id) => `${NOTE_KINDS[kind].storage.draft}.${id}`;
function readDraft(kind, id) {
  const d = readStored(draftKey(kind, id));
  return d && typeof d.text === "string" && Number.isInteger(d.base) ? d : null;
}
const writeDraft = (kind, id, draft) => writeStored(draftKey(kind, id), draft); // null forgets it

// The notes being edited in a NotesSection (`kind`, see NOTE_KINDS; `owner`, the thing they're about): the text, kept
// as a draft in this browser while it differs from what's saved, the browser asking before a tab with unsaved notes
// is closed, saving (stopped when it would overwrite what someone else saved meanwhile: `conflict`), and the status
// line saying where it stands.
export function useNoteDraft(kind, owner) {
  const data = useData();
  const { refresh } = data;
  const k = NOTE_KINDS[kind];
  const ownerId = owner.id;
  const { saved, rev, updatedAt } = k.read(owner);
  const onSave = ({ notes, baseRevision }) => k.save(ownerId, notes, baseRevision);

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
      k.apply(out, data); // just this one changed
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
  } else if (rev > 0 && saved) status = { tone: "good", text: `Saved. Last edited ${fmtWhen(updatedAt, "")}.` };
  else if (rev > 0) status = { tone: "faint", text: `Notes cleared ${fmtWhen(updatedAt, "")}.` };
  else status = { tone: "faint", text: "" }; // never had notes: nothing to say

  return { text, setText, phase, setPhase, conflict, dirty, busy, status, save, discard, useTheirs };
}
