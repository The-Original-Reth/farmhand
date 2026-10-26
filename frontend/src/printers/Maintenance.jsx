import { useEffect, useState } from "react";
import { Check, ChevronRight, Pencil, Wrench } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { headerButton, monoText, uiText } from "../styles.js";
import {
  addMaintenance,
  deleteMaintenance,
  getMaintenance,
  performMaintenance,
  serviceDone,
  setServiceEnabled,
  updateMaintenance,
} from "../api.js";
import { useData } from "../data.jsx";

import { ConfirmDialog, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { SegmentedToggle, TextField } from "../components/common/fields.jsx";
import { Badge, TrashButton } from "../components/common/ui.jsx";
import { fmtUnix } from "../lib/format.js";
import { NotesSection } from "../notes/NotesSection.jsx";

// ---- maintenance: lives on the printer, shared with Mainsail ----
const REMINDER_PARTS = [
  { key: "printtime", label: "Print time", unit: "hours" },
  { key: "filament", label: "Filament", unit: "metres" },
  { key: "date", label: "Time passed", unit: "days" },
];
const emptyReminder = () => ({
  type: null,
  filament: { bool: false, value: null },
  printtime: { bool: false, value: null },
  date: { bool: false, value: null },
});

// noFilament: the printer doesn't report filament use (PrusaLink), so a filament reminder isn't offered
function MaintenanceForm({ initial, onSubmit, onClose, actionLabel, noFilament = false }) {
  const parts = noFilament ? REMINDER_PARTS.filter((p) => p.key !== "filament") : REMINDER_PARTS;
  const [name, setName] = useState(initial?.name || "");
  const [note, setNote] = useState(initial?.note || "");
  const [reminder, setReminder] = useState(() => {
    const r = { ...emptyReminder(), ...(initial?.reminder || {}) };
    REMINDER_PARTS.forEach(({ key }) => (r[key] = { bool: !!r[key]?.bool, value: r[key]?.value ?? null }));
    return r;
  });
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const setPart = (key, change) => setReminder((r) => ({ ...r, [key]: { ...r[key], ...change } }));

  const submit = async () => {
    setErrorMsg(null);
    if (!name.trim()) return setErrorMsg("Give the maintenance a name.");
    if (reminder.type && !parts.some(({ key }) => reminder[key].bool)) {
      return setErrorMsg(`Pick at least one of print time${noFilament ? "" : ", filament"} or days for the reminder.`);
    }
    setSubmitting(true);
    try {
      const r = { type: reminder.type };
      REMINDER_PARTS.forEach(({ key }) => {
        const on = !!reminder.type && reminder[key].bool;
        r[key] = { bool: on, value: on ? Number(reminder[key].value) : null };
      });
      await onSubmit({ name: name.trim(), note: note.trim(), reminder: r });
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
      setSubmitting(false);
    }
  };

  const input = { background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, fontSize: fs(13), ...ui };
  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="e.g. Lubricate linear rails" />
      <div style={{ marginBottom: 14 }}>
        <div style={uiText(12, c.textFaint, { marginBottom: 5 })}>Note (optional)</div>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          placeholder="What to do, what to use"
          style={{ ...input, width: "100%", boxSizing: "border-box", padding: "8px 10px", resize: "vertical", lineHeight: 1.5 }}
        />
      </div>
      <div style={uiText(12, c.textFaint, { marginBottom: 5 })}>Reminder</div>
      <SegmentedToggle
        options={[{ value: "none", label: "No reminder" }, { value: "one-time", label: "Once" }, { value: "repeat", label: "Repeating" }]}
        value={reminder.type || "none"}
        onChange={(v) => setReminder((r) => ({ ...r, type: v === "none" ? null : v }))}
      />
      {reminder.type && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
          <div style={uiText(12, c.textMuted, { lineHeight: 1.5 })}>
            Due when any of these is reached, counted from now{reminder.type === "repeat" ? " and again each time it's done" : ""}:
          </div>
          {parts.map(({ key, label, unit }) => (
            <label key={key} style={{ display: "flex", alignItems: "center", gap: 10, ...ui, fontSize: fs(13), color: c.textMuted }}>
              <input type="checkbox" checked={reminder[key].bool} onChange={(e) => setPart(key, { bool: e.target.checked })} style={{ accentColor: c.amber }} />
              <span style={{ width: 90 }}>{label}</span>
              <input
                type="number"
                min="0"
                step="any"
                value={reminder[key].value ?? ""}
                disabled={!reminder[key].bool}
                onChange={(e) => setPart(key, { value: e.target.value === "" ? null : e.target.value })}
                style={{ ...input, width: 100, padding: "5px 8px", opacity: reminder[key].bool ? 1 : 0.5 }}
              />
              <span>{unit}</span>
            </label>
          ))}
        </div>
      )}
      <div style={uiText(11, c.textFaint, { marginBottom: 14, lineHeight: 1.5 })}>
        {noFilament
          ? "Kept in Farmhand: this printer has nowhere to keep maintenance itself. Print time counts the prints Farmhand has recorded."
          : "Saved on the printer, the same way Mainsail keeps its maintenance list, so it shows there too."}
      </div>
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel={actionLabel} submitting={submitting} errorMsg={errorMsg} submittingLabel="Saving…" />
    </>
  );
}

// message: replaces the usual "marks it done on the printer" explanation (the 1500-hour service lives in Farmhand)
function PerformMaintenanceForm({ entry, onSubmit, onClose, message }) {
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const submit = async () => {
    setSubmitting(true);
    setErrorMsg(null);
    try {
      await onSubmit({ note: note.trim() });
      onClose();
    } catch (e) {
      setErrorMsg(e.message || String(e));
      setSubmitting(false);
    }
  };
  return (
    <>
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 12 })}>
        {message || (
          <>
            Marks <b style={{ color: c.heading }}>{entry.name}</b> as done on the printer, now. Mainsail will show it as done too.
            {entry.reminder?.type === "repeat" && " Its next round starts counting straight away."}
          </>
        )}
      </div>
      <div style={uiText(12, c.textFaint, { marginBottom: 5 })}>What was done (optional)</div>
      <textarea
        data-testid="maintenance-done-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={3}
        autoFocus
        style={{ width: "100%", boxSizing: "border-box", background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, padding: "8px 10px", fontSize: fs(13), ...ui, resize: "vertical", marginBottom: 14 }}
      />
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel="Mark done" submitting={submitting} errorMsg={errorMsg} submittingLabel="Saving…" />
    </>
  );
}

// "12 / 50 hours printed", "3.4 / 10 m of filament", "8 / 30 days"
const checkText = (ch) => {
  const n = (v) => v.toLocaleString(undefined, { maximumFractionDigits: v < 10 ? 1 : 0 });
  const label = { printtime: "hours printed", filament: "m of filament", date: "days" }[ch.kind];
  return `${n(Math.max(0, ch.used))} / ${n(ch.limit)} ${label}`;
};

function MaintenanceRow({ entry, onDone, onEdit, onDelete }) {
  const done = entry.state === "done";
  return (
    <div data-testid="maintenance-row" data-state={entry.state} style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "10px 14px", borderTop: `1px solid ${c.border}` }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={uiText(14, done ? c.textMuted : c.heading)}>{entry.name}</span>
          {entry.state === "due" && <Badge tone="danger">due</Badge>}
          {entry.state === "ok" && <Badge tone="green">ok</Badge>}
          {entry.reminder?.type === "repeat" && <Badge>repeats</Badge>}
          {done && <Badge>done {fmtUnix(entry.end_time)}</Badge>}
        </div>
        {entry.note && <div style={uiText(12, c.textMuted, { marginTop: 3, whiteSpace: "pre-wrap" })}>{entry.note}</div>}
        {entry.checks?.length > 0 && (
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
            {entry.checks.map((ch) => (
              <span key={ch.kind} style={monoText(11, ch.due ? c.danger : c.textFaint)}>
                {checkText(ch)}
              </span>
            ))}
          </div>
        )}
        {done && entry.perform_note && <div style={uiText(12, c.textFaint, { marginTop: 3 })}>“{entry.perform_note}”</div>}
      </div>
      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
        {!done && (
          <button data-testid="maintenance-done" onClick={onDone} style={{ ...headerButton(), color: entry.state === "due" ? c.amber : c.textMuted, borderColor: entry.state === "due" ? c.amber : c.border }}>
            <Check size={12} />
            Done
          </button>
        )}
        {!done && (
          <button onClick={onEdit} title="Edit" aria-label="Edit" style={{ ...headerButton(), padding: 0, width: 26, justifyContent: "center" }}>
            <Pencil size={12} />
          </button>
        )}
        <TrashButton title="Delete this maintenance entry" onClick={onDelete} />
      </div>
    </div>
  );
}

// The 1500-hour service, kept in Farmhand: due once the printer's synced print time has grown by 1500 hours since
// the count started (its first sync, or the last time this was marked done). Shown whether or not the printer answers.
function ServiceReminder({ printer }) {
  const { refresh } = useData();
  const [dialog, setDialog] = useState(null); // "done" | null
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const s = printer.service;
  const interval = s.interval_hours;
  const since = s.hours_since ?? 0;
  const pct = Math.min(100, (since / interval) * 100);
  const n = (v) => Math.floor(v).toLocaleString();

  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      await setServiceEnabled(printer.id, !s.enabled);
      await refresh();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  let text;
  if (s.state === "waiting") text = "Starts counting once the printer's print time has been synced.";
  else if (s.state === "off") text = `Switched off for this printer. ${n(since)} print hours since it was last reset.`;
  else text = `${n(since)} / ${n(interval)} print hours since ${s.last_done ? "the last service" : "counting started"}${s.started_at ? ` (${new Date(s.started_at).toLocaleDateString()})` : ""}.`;

  return (
    <div data-testid="service-reminder" data-state={s.state}>
    <div style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "10px 14px" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={uiText(14, s.state === "off" ? c.textMuted : c.heading)}>{n(interval)}-hour service</span>
          {s.state === "due" && <Badge tone="danger">due</Badge>}
          {s.state === "ok" && <Badge tone="green">ok</Badge>}
          {s.state === "off" && <Badge>off</Badge>}
          <Badge>repeats · kept in Farmhand</Badge>
        </div>
        <div style={monoText(11, s.state === "due" ? c.danger : c.textFaint, { marginTop: 4 })}>{text}</div>
        {(s.state === "ok" || s.state === "due") && (
          <div style={{ height: 4, borderRadius: 2, background: c.panelAlt, marginTop: 6, maxWidth: 320, overflow: "hidden" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: s.state === "due" ? c.danger : c.teal }} />
          </div>
        )}
        {s.last_done && (
          <div style={uiText(12, c.textFaint, { marginTop: 4 })}>
            Last done {new Date(s.last_done.done_at).toLocaleDateString()}, after {n(s.last_done.hours)} hours{s.last_done.note ? ` — “${s.last_done.note}”` : ""}
          </div>
        )}
        {error && <div style={uiText(12, c.amber, { marginTop: 4 })}>{error}</div>}
      </div>
      {s.state !== "waiting" && (
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          {s.enabled && (
            <button
              data-testid="service-done"
              onClick={() => setDialog("done")}
              style={{ ...headerButton(), color: s.state === "due" ? c.amber : c.textMuted, borderColor: s.state === "due" ? c.amber : c.border }}
            >
              <Check size={12} />
              Done
            </button>
          )}
          <button data-testid="service-toggle" onClick={toggle} disabled={busy} style={{ ...headerButton(), opacity: busy ? 0.55 : 1 }}>
            {s.enabled ? "Turn off" : "Turn on"}
          </button>
        </div>
      )}
    </div>
      <div data-testid="service-notes" style={{ padding: "0 14px 12px" }}>
        <NotesSection key={printer.id} kind="service" owner={printer} />
      </div>
      {dialog === "done" && (
        <Modal title={`${n(interval)}-hour service done`} onClose={() => setDialog(null)} width={440}>
          <PerformMaintenanceForm
            entry={{ name: `the ${n(interval)}-hour service`, reminder: { type: null } }}
            message={`The next ${n(interval)} print hours count from the printer's print time now. This is kept in Farmhand, not on the printer.`}
            onClose={() => setDialog(null)}
            onSubmit={async ({ note }) => {
              await serviceDone(printer.id, { note });
              await refresh();
            }}
          />
        </Modal>
      )}
    </div>
  );
}

// onDueCount(n): told how many reminders are due (the 1500-hour service included), for the folded group's heading.
// A PrusaLink printer's maintenance is kept in Farmhand, so it's always there.
export function MaintenanceSection({ printer, reachable, onDueCount }) {
  const inFarmhand = printer.connectionType === "prusalink";
  const [data, setData] = useState(null); // { entries, totals }
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null); // { kind: "add" | "edit" | "done" | "delete", entry }
  const [showDone, setShowDone] = useState(false);

  const load = async () => {
    try {
      setData(await getMaintenance(printer.id));
      setError(null);
    } catch (e) {
      setError(e.message || String(e));
    }
  };
  useEffect(() => {
    setData(null);
    setError(null);
    setShowDone(false);
    if (reachable) load();
  }, [printer.id, reachable]);

  const entries = data?.entries || [];
  const order = { due: 0, ok: 1, no_reminder: 2 };
  const open = entries.filter((e) => e.state !== "done").sort((a, b) => order[a.state] - order[b.state]);
  const done = entries.filter((e) => e.state === "done");
  const dueCount = open.filter((e) => e.state === "due").length + (printer.service.state === "due" ? 1 : 0);
  const close = () => setDialog(null);
  useEffect(() => {
    onDueCount?.(dueCount);
  }, [dueCount]);

  return (
    <div data-testid="maintenance-section">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(13), color: c.textFaint }}>
          Maintenance
          {dueCount > 0 && <Badge tone="danger">{dueCount} due</Badge>}
        </div>
        <button
          data-testid="maintenance-add"
          onClick={() => setDialog({ kind: "add" })}
          disabled={!reachable || !data}
          style={{ ...headerButton(), opacity: reachable && data ? 1 : 0.55, cursor: reachable && data ? "pointer" : "default" }}
        >
          <Wrench size={12} />
          Add maintenance
        </button>
      </div>
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel }}>
        <ServiceReminder printer={printer} />
        <div style={{ borderTop: `1px solid ${c.border}` }}>
        {!reachable ? (
          <div style={uiText(13, c.textMuted, { padding: 14, lineHeight: 1.6 })}>
            The rest of the maintenance is kept on the printer (shared with Mainsail), so it shows once the printer can be reached.
          </div>
        ) : error ? (
          <div style={uiText(13, c.amber, { padding: 14 })}>Couldn't load maintenance: {error}</div>
        ) : !data ? (
          <div style={uiText(13, c.textFaint, { padding: 14 })}>Loading…</div>
        ) : entries.length === 0 ? (
          <div style={uiText(13, c.textMuted, { padding: 14 })}>No other maintenance recorded on this printer yet.</div>
        ) : (
          <div style={{ marginTop: -1 }}>
            {open.map((e) => (
              <MaintenanceRow
                key={e.id}
                entry={e}
                onDone={() => setDialog({ kind: "done", entry: e })}
                onEdit={() => setDialog({ kind: "edit", entry: e })}
                onDelete={() => setDialog({ kind: "delete", entry: e })}
              />
            ))}
            {done.length > 0 && (
              <button
                data-testid="maintenance-show-done"
                onClick={() => setShowDone(!showDone)}
                style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", textAlign: "left", padding: "8px 14px", border: "none", borderTop: `1px solid ${c.border}`, background: "none", color: c.textMuted, ...ui, fontSize: fs(12), cursor: "pointer" }}
              >
                <ChevronRight size={12} style={{ transform: showDone ? "rotate(90deg)" : "none" }} />
                {showDone ? "Hide" : "Show"} {done.length} done
              </button>
            )}
            {showDone && done.map((e) => <MaintenanceRow key={e.id} entry={e} onDelete={() => setDialog({ kind: "delete", entry: e })} />)}
          </div>
        )}
        </div>
      </div>

      {dialog?.kind === "add" && (
        <Modal title="Add maintenance" onClose={close} width={480}>
          <MaintenanceForm actionLabel="Add" noFilament={inFarmhand} onClose={close} onSubmit={async (v) => setData(await addMaintenance(printer.id, v))} />
        </Modal>
      )}
      {dialog?.kind === "edit" && (
        <Modal title="Edit maintenance" onClose={close} width={480}>
          <MaintenanceForm
            initial={dialog.entry}
            actionLabel="Save"
            noFilament={inFarmhand}
            onClose={close}
            onSubmit={async (v) => setData(await updateMaintenance(printer.id, dialog.entry.id, v))}
          />
        </Modal>
      )}
      {dialog?.kind === "done" && (
        <Modal title="Maintenance done" onClose={close} width={440}>
          <PerformMaintenanceForm
            entry={dialog.entry}
            message={inFarmhand ? <>Marks <b style={{ color: c.heading }}>{dialog.entry.name}</b> as done, now. It's kept in Farmhand.</> : undefined}
            onClose={close}
            onSubmit={async (v) => setData(await performMaintenance(printer.id, dialog.entry.id, v))}
          />
        </Modal>
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog title="Delete maintenance" onClose={close} onConfirm={async () => setData(await deleteMaintenance(printer.id, dialog.entry.id))}>
          {inFarmhand ? (
            <>Delete <b style={{ color: c.heading }}>{dialog.entry.name}</b>? This can't be undone.</>
          ) : (
            <>Delete <b style={{ color: c.heading }}>{dialog.entry.name}</b> from the printer? It's removed from Mainsail too. This can't be undone.</>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
