import { useEffect, useRef, useState } from "react";
import { ExternalLink, Upload } from "lucide-react";
import { c } from "../theme.js";
import { headerButton, uiText } from "../styles.js";
import { errorText, getPrintStats, getPrusaLinkStatus, sendPrint } from "../api.js";

import { ConfirmDialog } from "../components/common/dialogs.jsx";
import { SectionToggle, StatTile } from "../components/common/ui.jsx";
import { fmtDuration, formatBytes } from "../lib/format.js";
import { ArchiveSummary, ConnectionLine, useLiveStatus } from "./connectionCard.jsx";
import { JobProgress } from "./JobProgress.jsx";

// ---- a PrusaLink printer (Prusa Core One, MK4, XL...) ----
const PRUSALINK_LOOK_MS = 10000; // how often the open printer page looks at the printer
const PRUSALINK_STATES = {
  IDLE: "Idle", READY: "Ready", BUSY: "Busy", PRINTING: "Printing", PAUSED: "Paused", FINISHED: "Finished",
  STOPPED: "Stopped", ERROR: "Error", ATTENTION: "Needs attention at the printer",
};
const PRUSALINK_FREE = ["IDLE", "READY", "FINISHED", "STOPPED"]; // states a new print can be sent in

// The printer's PrusaLink as the printer page sees it: its live status, looked at every few seconds while the page is
// open. Each look also brings Farmhand's record of its prints up to date (PrusaLink keeps no history of its own).
// `key` restarts it when the printer or its login changes. onChanged: called when a print starts or ends (the page
// reloads the printer, whose service hours have moved on); syncTick goes up whenever the record moved, so the
// history list reloads.
export function usePrusaLink(printerId, key, onChanged) {
  const [status, setStatus] = useLiveStatus(); // GET /printers/{id}/prusalink
  const [stats, setStats] = useState(null); // GET /printers/{id}/print-stats
  const [syncTick, setSyncTick] = useState(0);
  const current = useRef(null);
  const marks = useRef({ history: null, job: null });

  const look = async (id = printerId) => {
    let s;
    try {
      s = await getPrusaLinkStatus(id);
    } catch (e) {
      s = { reachable: false, error: errorText(e) };
    }
    if (current.current !== key) return;
    setStatus(s);
    const job = JSON.stringify([s.job?.id ?? null, s.job?.state ?? null]);
    const history = JSON.stringify([job, Math.floor((s.job?.progress ?? 0) / 5), s.totals?.total_jobs ?? null]);
    if (history !== marks.current.history) {
      marks.current.history = history;
      getPrintStats(id).then((st) => current.current === key && setStats(st)).catch(() => {});
      setSyncTick((t) => t + 1);
    }
    if (job !== marks.current.job) {
      const first = marks.current.job === null;
      marks.current.job = job;
      if (!first) await onChanged?.();
    }
  };

  useEffect(() => {
    if (!printerId) return undefined;
    current.current = key;
    marks.current = { history: null, job: null };
    setStatus(null);
    setStats(null);
    look(printerId);
    const timer = setInterval(() => {
      if (!document.hidden) look(printerId);
    }, PRUSALINK_LOOK_MS);
    return () => {
      current.current = null;
      clearInterval(timer);
    };
  }, [key]);

  return { status, stats, syncTick, look: () => look() };
}

const fmtTemp = (now, target) => (now == null ? "—" : `${Math.round(now)}°${target ? ` / ${Math.round(target)}°` : ""}`);

// Live status (state, temperatures, the print running), Farmhand's statistics for it, "Open PrusaLink" and "Send a print"
export function PrusaLinkCard({ printer, pl, open = true, onToggle }) {
  const { status, stats } = pl;
  const [chosen, setChosen] = useState(null); // the file picked to send, waiting for the go-ahead
  const fileInput = useRef(null);
  const totals = stats?.totals || status?.totals;
  const archive = stats?.archive;
  const job = status?.job;
  const free = !!status?.reachable && PRUSALINK_FREE.includes(status.state);

  let dot = c.textFaint;
  let line = "Checking the printer…";
  if (status) {
    if (status.reachable) {
      dot = status.state === "ERROR" || status.state === "ATTENTION" ? c.danger : status.state === "PRINTING" ? c.teal : c.green;
      const what = [status.printer_type === "COREONE" ? "Core One" : status.printer_type, status.firmware && `firmware ${status.firmware}`].filter(Boolean).join(" · ");
      line = `${PRUSALINK_STATES[status.state] || status.state || "Connected"}${what ? ` · ${what}` : ""}`;
    } else {
      dot = c.danger;
      line = status.error || "Can't reach PrusaLink.";
    }
  }

  return (
    <div data-testid="prusalink-card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: open ? 10 : 0, flexWrap: "wrap" }}>
        <SectionToggle open={open} onToggle={onToggle} controlsId="prusalink-card-body" testId="toggle-connection" indent={20}>
          Live status and statistics
        </SectionToggle>
        {open && (
        <div style={{ display: "flex", gap: 8 }}>
          {printer.prusalinkUrl && (
            <a data-testid="open-prusalink" href={printer.prusalinkUrl} target="_blank" rel="noreferrer" style={headerButton()} title={printer.prusalinkUrl}>
              <ExternalLink size={12} />
              Open PrusaLink
            </a>
          )}
          <input
            ref={fileInput}
            type="file"
            accept=".bgcode,.gcode"
            style={{ display: "none" }}
            onChange={(e) => {
              if (e.target.files?.[0]) setChosen(e.target.files[0]);
              e.target.value = "";
            }}
          />
          <button
            data-testid="prusalink-send"
            onClick={() => fileInput.current?.click()}
            disabled={!free}
            title={free ? "Send a sliced .bgcode file to the printer and start it" : status?.reachable ? "The printer is busy" : "The printer can't be reached right now"}
            style={{ ...headerButton(), opacity: free ? 1 : 0.55, cursor: free ? "pointer" : "default" }}
          >
            <Upload size={12} />
            Send a print
          </button>
        </div>
        )}
      </div>
      {open && (
      <div id="prusalink-card-body" style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 14 }}>
        <ConnectionLine testId="prusalink-status" dot={dot} line={line} reachable={status?.reachable} url={printer.prusalinkUrl} />

        {job && (
          <JobProgress
            testId="prusalink-job"
            file={job.file}
            progress={job.progress}
            printed={job.time_printing}
            left={job.state === "PRINTING" ? job.time_remaining : null}
            paused={job.state === "PAUSED"}
            note={job.state && job.state !== "PRINTING" ? (PRUSALINK_STATES[job.state] || job.state).toLowerCase() : null}
          />
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 8, marginTop: 12 }}>
          <StatTile label="Nozzle" value={fmtTemp(status?.temps?.temp_nozzle, status?.temps?.target_nozzle)} hint="Now / target" />
          <StatTile label="Bed" value={fmtTemp(status?.temps?.temp_bed, status?.temps?.target_bed)} hint="Now / target" />
          <StatTile label="Prints" value={totals ? totals.total_jobs.toLocaleString() : "—"} hint="Prints Farmhand has recorded" />
          <StatTile label="Print time" value={totals ? fmtDuration(totals.total_print_time) : "—"} hint="Time spent printing, as Farmhand has recorded it" />
          <StatTile label="Longest print" value={totals ? fmtDuration(totals.longest_print) : "—"} />
        </div>

        <div data-testid="prusalink-note" style={uiText(12, c.textFaint, { marginTop: 10, lineHeight: 1.6 })}>
          Prusa printers keep no print history, so Farmhand notes each print while it runs: every minute, and every few seconds
          while this page is open. A print that starts and ends between two looks is missed.
          <ArchiveSummary archive={archive} failedLabel="failed or unknown" />
        </div>
      </div>
      )}

      {chosen && (
        <ConfirmDialog
          title="Send a print"
          confirmLabel="Send and print"
          tone="amber"
          onClose={() => setChosen(null)}
          onConfirm={async () => {
            await sendPrint(printer.id, chosen);
            await pl.look();
          }}
        >
          Send <b style={{ color: c.heading }}>{chosen.name}</b> ({formatBytes(chosen.size)}) to <b style={{ color: c.heading }}>{printer.name}</b> and
          start printing it now? Make sure the bed is clear and the right filament is loaded. It goes on the printer's USB
          drive, replacing a file of the same name.
        </ConfirmDialog>
      )}
    </div>
  );
}
