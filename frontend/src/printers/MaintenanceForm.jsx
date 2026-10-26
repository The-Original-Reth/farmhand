import { useState } from "react";
import { c, fs, ui } from "../theme.js";
import { errorText } from "../api.js";
import { uiText } from "../styles.js";
import { ModalActions } from "../components/common/dialogs.jsx";
import { SegmentedToggle, TextField } from "../components/common/fields.jsx";

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
export function MaintenanceForm({ initial, onSubmit, onClose, actionLabel, noFilament = false }) {
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
      setErrorMsg(errorText(e));
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
export function PerformMaintenanceForm({ entry, onSubmit, onClose, message }) {
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
      setErrorMsg(errorText(e));
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
