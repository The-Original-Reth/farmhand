import { saveBundleNotes, saveModelNotes, savePrinterNotes, saveServiceNotes } from "../api.js";

// Every kind of notes Farmhand keeps, in one place: where the text is on the thing it's about (read), how it's saved
// (save: resolves to the saved notes; apply: puts what the save answered in the page's data), what the box says, and the keys this browser keeps an unsaved draft and the
// folded/open choice under. The keys are the ones each kind has always used, so drafts and folding carry over.
export const NOTE_KINDS = {
  model: {
    read: (m) => ({ saved: m.notes, rev: m.notesRevision, updatedAt: m.notesUpdatedAt }),
    save: (id, notes, baseRevision) => saveModelNotes({ modelId: id, notes, baseRevision }),
    apply: (out, data) => data.putModel(out),
    description: () => "About this model as a whole — print settings that work, where it came from, licence, things to remember.",
    placeholder: "Nothing written yet. Notes you add here are kept with this model and can be searched from the Models page.",
    storage: { draft: "farmhand.notesDraft", collapsed: "farmhand.notesCollapsed.v2" },
  },
  printer: {
    read: (p) => ({ saved: p.notes, rev: p.notesRevision, updatedAt: p.notesUpdatedAt }),
    save: (id, notes, baseRevision) => savePrinterNotes({ printerId: id, notes, baseRevision }),
    apply: (out, data) => data.putPrinter(out),
    description: () => "About this printer — nozzle and bed, calibration, maintenance, quirks, where it lives.",
    placeholder: "Nothing written yet. Notes you add here are kept with this printer.",
    storage: { draft: "farmhand.printerNotesDraft", collapsed: "farmhand.printerNotesCollapsed.v2" },
  },
  // one 3MF entry, shared by all its versions
  bundle: {
    read: (b) => ({ saved: b.notes, rev: b.notesRevision, updatedAt: b.notesUpdatedAt }),
    save: (id, notes, baseRevision) => saveBundleNotes({ bundleId: id, notes, baseRevision }),
    apply: (out, data) => data.putBundle(out),
    description: () => "About this 3MF — what the settings are tuned for, plate setup, how it printed.",
    placeholder: "Nothing written yet. Notes you add here are kept with this 3MF and every version of it.",
    storage: { draft: "farmhand.bundleNotesDraft", collapsed: "farmhand.bundleNotesCollapsed.v2" },
  },
  // a printer's 1500-hour service: the owner is the printer
  service: {
    read: (p) => ({ saved: p.service.notes, rev: p.service.notes_revision, updatedAt: p.service.notes_updated_at }),
    save: (id, notes, baseRevision) => saveServiceNotes({ printerId: id, notes, baseRevision }),
    apply: (out, data) => data.putPrinter(out.printer),
    description: (p) => `About this printer's ${Math.floor(p.service.interval_hours).toLocaleString()}-hour service: what it involves, parts to have ready.`,
    placeholder: "Nothing written yet. Notes you add here are kept in Farmhand with this printer's service.",
    storage: { draft: "farmhand.serviceNotesDraft", collapsed: "farmhand.serviceNotesCollapsed" },
  },
};
