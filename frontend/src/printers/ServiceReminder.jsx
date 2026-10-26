import { useState } from "react";
import { Check } from "lucide-react";
import { c } from "../theme.js";
import { errorText, serviceDone, setServiceEnabled } from "../api.js";
import { headerButton, monoText, uiText } from "../styles.js";
import { useData } from "../data.jsx";
import { Modal } from "../components/common/dialogs.jsx";
import { Badge } from "../components/common/ui.jsx";
import { NotesSection } from "../notes/NotesSection.jsx";

import { PerformMaintenanceForm } from "./MaintenanceForm.jsx";

// The 1500-hour service, kept in Farmhand: due once the printer's synced print time has grown by 1500 hours since
// the count started (its first sync, or the last time this was marked done). Shown whether or not the printer answers.
export function ServiceReminder({ printer }) {
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
      setError(errorText(e));
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
