import { useEffect, useRef, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { headerButton, monoText, uiText } from "../styles.js";
import { errorText, getMoonrakerStatus, getPrintStats, syncPrinterHistory } from "../api.js";

import { StatTile } from "../components/common/ui.jsx";
import { fmtDuration, fmtMetres, fmtWhen } from "../lib/format.js";
import { JobProgress } from "./JobProgress.jsx";

const MOONRAKER_LOOK_MS = 10000; // how often the open printer page looks at the printer (connection and the print running)

// The printer's Moonraker as the printer page sees it. On opening a printer: check the connection, show what
// Farmhand already has, then sync the history in the background if the printer answers. While the page is open it
// looks again every few seconds, so a running print's progress stays current; when a print starts or ends the
// history is synced again. `key` restarts all of it when the printer or its address changes.
// onSynced: called after each successful sync (the page reloads the printer, whose service hours have moved on)
export function useMoonraker(printerId, key, onSynced) {
  const [status, setStatusNow] = useState(null); // GET /printers/{id}/moonraker
  const seen = useRef("");
  const setStatus = (s) => {
    const json = JSON.stringify(s);
    if (json !== seen.current) setStatusNow(s); // an answer the same as the last redraws nothing
    seen.current = json;
  };
  const [stats, setStats] = useState(null); // GET /printers/{id}/print-stats
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState(null);
  const [syncTick, setSyncTick] = useState(0); // goes up after every sync, so the history list reloads
  const current = useRef(null);
  const printing = useRef(null); // the print last seen running ("file|state"), to notice one starting or ending

  const sync = async (id = printerId) => {
    setSyncing(true);
    try {
      await syncPrinterHistory(id);
      if (current.current === key) setSyncError(null);
      await onSynced?.();
    } catch (e) {
      if (current.current === key) setSyncError(errorText(e));
    }
    try {
      const s = await getPrintStats(id);
      if (current.current === key) setStats(s);
    } catch {
      /* the stats stay as they were */
    }
    if (current.current === key) {
      setSyncing(false);
      setSyncTick((t) => t + 1);
    }
  };

  useEffect(() => {
    if (!printerId) return undefined;
    current.current = key;
    setStatus(null);
    setStats(null);
    setSyncError(null);
    (async () => {
      const [s, st] = await Promise.all([
        getMoonrakerStatus(printerId).catch((e) => ({ reachable: false, error: errorText(e) })),
        getPrintStats(printerId).catch(() => null),
      ]);
      if (current.current !== key) return;
      setStatus(s);
      setStats(st);
      printing.current = s.print ? `${s.print.file}|${s.print.state}` : "";
      if (s.reachable) await sync(printerId);
    })();
    const timer = setInterval(async () => {
      if (document.hidden || printing.current === null) return; // the first look hasn't answered yet
      const s = await getMoonrakerStatus(printerId).catch((e) => ({ reachable: false, error: errorText(e) }));
      if (current.current !== key) return;
      setStatus(s);
      if (!s.reachable) return;
      const now = s.print ? `${s.print.file}|${s.print.state}` : "";
      if (now !== printing.current) {
        printing.current = now;
        await sync(printerId); // a print started, paused or ended: bring the history and statistics up to date
      }
    }, MOONRAKER_LOOK_MS);
    return () => {
      current.current = null;
      printing.current = null;
      clearInterval(timer);
    };
  }, [key]);

  return { status, stats, syncing, syncError, syncTick, sync: () => sync() };
}

// Connection + the printer's own lifetime statistics, with "Open Mainsail" and "Sync now"
export function MoonrakerCard({ printer, mr }) {
  const { status, stats, syncing, syncError } = mr;
  const totals = stats?.totals;
  const archive = stats?.archive;
  let dot = c.textFaint;
  let line = "Checking the connection…";
  if (status) {
    if (status.reachable) {
      const ready = status.klippy_state === "ready";
      dot = ready ? c.green : c.amber;
      line = `Connected${status.klippy_state ? ` · Klipper ${status.klippy_state}` : ""}${status.moonraker_version ? ` · Moonraker ${status.moonraker_version}` : ""}`;
    } else {
      dot = c.danger;
      line = status.error || "Can't reach Moonraker.";
    }
  }
  const failed = archive ? archive.jobs - (archive.by_status.completed || 0) - (archive.by_status.in_progress || 0) - (archive.by_status.cancelled || 0) : 0;
  const lastSync = stats?.last_sync_at || status?.last_sync_at;
  const lastSyncError = syncError || stats?.last_sync_error;

  return (
    <div data-testid="moonraker-card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <div style={uiText(13, c.textFaint)}>Connection and statistics</div>
        <div style={{ display: "flex", gap: 8 }}>
          {printer.mainsailUrl && (
            <a data-testid="open-mainsail" href={printer.mainsailUrl} target="_blank" rel="noreferrer" style={headerButton()} title={printer.mainsailUrl}>
              <ExternalLink size={12} />
              Open Mainsail
            </a>
          )}
          <button
            data-testid="moonraker-sync"
            onClick={mr.sync}
            disabled={syncing || !status?.reachable}
            title={status?.reachable ? "Copy the printer's latest print history into Farmhand" : "The printer can't be reached right now"}
            style={{ ...headerButton(), opacity: syncing || !status?.reachable ? 0.55 : 1, cursor: syncing || !status?.reachable ? "default" : "pointer" }}
          >
            <RefreshCw size={12} style={syncing ? { animation: "fh-spin 1s linear infinite" } : undefined} />
            {syncing ? "Syncing…" : "Sync now"}
          </button>
        </div>
      </div>
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 14 }}>
        <div data-testid="moonraker-status" style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: status?.reachable ? c.textPrimary : c.textMuted, lineHeight: 1.5 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: dot, flexShrink: 0, marginTop: 6 }} />
          <span>
            {line}
            {status?.reachable && printer.moonrakerUrl && (
              <span style={monoText(11, c.textFaint, { marginLeft: 8 })}>{printer.moonrakerUrl}</span>
            )}
          </span>
        </div>

        {status?.print && (
          <JobProgress
            testId="moonraker-job"
            file={status.print.file}
            progress={status.print.progress}
            printed={status.print.print_duration}
            left={status.print.state === "printing" ? status.print.time_remaining : null}
            paused={status.print.state === "paused"}
            note={status.print.state === "paused" ? "paused" : null}
          />
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 8, marginTop: 12 }}>
          <StatTile label="Prints" value={totals ? totals.total_jobs.toLocaleString() : "—"} hint="All jobs the printer has recorded" />
          <StatTile label="Print time" value={totals ? fmtDuration(totals.total_print_time) : "—"} hint="Time spent printing (pauses not counted)" />
          <StatTile label="Filament used" value={totals ? fmtMetres(totals.total_filament_used) : "—"} />
          <StatTile label="Longest print" value={totals ? fmtDuration(totals.longest_print) : "—"} />
        </div>

        <div data-testid="moonraker-sync-state" style={uiText(12, lastSyncError ? c.amber : c.textFaint, { marginTop: 10, lineHeight: 1.6 })}>
          {lastSyncError
            ? `Last sync failed: ${lastSyncError}${lastSync ? ` The figures above are from ${fmtWhen(lastSync)}.` : ""}`
            : lastSync
              ? `Statistics from the printer, as of ${fmtWhen(lastSync)}.`
              : "Not synced yet."}
          {archive && archive.jobs > 0 && (
            <div>
              Farmhand has {archive.jobs.toLocaleString()} print{archive.jobs === 1 ? "" : "s"} on record:{" "}
              {(archive.by_status.completed || 0).toLocaleString()} completed, {(archive.by_status.cancelled || 0).toLocaleString()} cancelled,{" "}
              {failed.toLocaleString()} failed{archive.by_status.in_progress ? `, ${archive.by_status.in_progress} in progress` : ""}.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
