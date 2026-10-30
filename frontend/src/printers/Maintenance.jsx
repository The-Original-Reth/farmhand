import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight, Pencil, Wrench } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import {
  addMaintenance,
  deleteMaintenance,
  errorText,
  getMaintenance,
  performMaintenance,
  updateMaintenance,
} from "../api.js";
import { foldHeading, headerButton, monoText, panelBox, uiText } from "../styles.js";
import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { Badge, SectionToggle, TrashButton } from "../components/common/ui.jsx";
import { fmtUnix } from "../lib/format.js";

import { MaintenanceForm, PerformMaintenanceForm } from "./MaintenanceForm.jsx";
import { ServiceReminder } from "./ServiceReminder.jsx";

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

// onDueCount(n): told how many reminders are due (the 1500-hour service included), for the folded group's heading.
// A PrusaLink printer's maintenance is kept in Farmhand, so it's always there.
// Folds away (open/onToggle); folded, it still says how many are due.
export function MaintenanceSection({ printer, reachable, onDueCount, open: unfolded = true, onToggle }) {
  const inFarmhand = printer.connectionType === "prusalink";
  const [data, setData] = useState(null); // { entries, totals }
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null); // { kind: "add" | "edit" | "done" | "delete", entry }
  const [showDone, setShowDone] = useState(false);

  // Only the latest answer counts: switching printers while one is on its way must not show the last printer's list
  const ask = useRef(0);
  const load = async () => {
    const mine = ++ask.current;
    try {
      const d = await getMaintenance(printer.id);
      if (mine !== ask.current) return;
      setData(d);
      setError(null);
    } catch (e) {
      if (mine === ask.current) setError(errorText(e));
    }
  };
  useEffect(() => {
    ask.current++; // whatever was asked for the last printer is no longer wanted
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
      <div style={{ ...foldHeading(unfolded), flexWrap: "nowrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <SectionToggle open={unfolded} onToggle={onToggle} controlsId="maintenance-body" testId="toggle-maintenance" indent={20}>
            Maintenance
          </SectionToggle>
          {dueCount > 0 && <Badge tone="danger">{dueCount} due</Badge>}
        </div>
        {unfolded && (
        <button
          data-testid="maintenance-add"
          onClick={() => setDialog({ kind: "add" })}
          disabled={!reachable || !data}
          style={{ ...headerButton(), opacity: reachable && data ? 1 : 0.55, cursor: reachable && data ? "pointer" : "default" }}
        >
          <Wrench size={12} />
          Add maintenance
        </button>
        )}
      </div>
      {unfolded && (
      <div id="maintenance-body" style={panelBox()}>
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
      )}

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
