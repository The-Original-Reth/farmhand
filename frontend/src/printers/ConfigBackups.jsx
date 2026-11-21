import { useEffect, useRef, useState } from "react";
import { ChevronRight, Database, Download, History, Save } from "lucide-react";
import { c, ui } from "../theme.js";
import {
  configBackupZipUrl,
  deleteConfigBackup,
  errorText,
  getConfigBackups,
  restoreConfigBackupDatabase,
  restoreConfigBackupFile,
  takeConfigBackup,
} from "../api.js";
import { foldHeading, headerButton, monoText, panelBox, uiText } from "../styles.js";
import { ConfirmDialog } from "../components/common/dialogs.jsx";
import { Badge, SectionToggle, TrashButton } from "../components/common/ui.jsx";
import { formatBytes, fmtWhen, plural } from "../lib/format.js";
import { BackupFiles } from "./configBackups/BackupFiles.jsx";
import { FileDialog } from "./configBackups/FileDialog.jsx";
import { RestoreDialog } from "./configBackups/RestoreDialog.jsx";
import { Schedule } from "./configBackups/Schedule.jsx";
import { SshDialog } from "./configBackups/SshDialog.jsx";
import { TRIGGER, changesHint, changesText } from "./configBackups/shared.js";
import { klipperUi } from "./webUi.js";

// The printer's config backups, below its print history. Folds away (open/onToggle); loads either way, so the heading
// can say how many are kept.
export function ConfigBackupsSection({ printer, open = true, onToggle }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [message, setMessage] = useState(null);
  const [expanded, setExpanded] = useState(null); // the backup whose files show
  const [dialog, setDialog] = useState(null); // { kind: "file" | "restore" | "delete", backup, file, mode }
  const ask = useRef(0);

  const load = async () => {
    const mine = ++ask.current;
    try {
      const d = await getConfigBackups(printer.id);
      if (mine === ask.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (mine === ask.current) setError(errorText(e));
    }
  };
  useEffect(() => {
    setData(null);
    setExpanded(null);
    setMessage(null);
    setActionError(null);
    load();
  }, [printer.id]);

  const backUpNow = async () => {
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const d = await takeConfigBackup(printer.id);
      ask.current++;
      setData(d);
      setExpanded(d.id);
    } catch (e) {
      setActionError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const backups = data?.backups || [];
  const close = () => setDialog(null);
  const supported = data?.supported !== false && printer.connectionType !== "prusalink";

  return (
    <div data-testid="config-backups">
      <div style={foldHeading(open)}>
        <SectionToggle open={open} onToggle={onToggle} controlsId="config-backups-body" testId="toggle-backups">
          Backups
          {supported && data && <span style={{ color: c.textFaint }}>({backups.length} of {data.keep})</span>}
        </SectionToggle>
        {open && supported && (
          <button data-testid="backup-now" onClick={backUpNow} disabled={busy || !data} style={{ ...headerButton(), opacity: busy || !data ? 0.55 : 1 }}>
            <Save size={12} />
            {busy ? "Backing up…" : "Back up now"}
          </button>
        )}
      </div>
      {open && (
        <div id="config-backups-body" style={panelBox()}>
          {!supported ? (
            <div style={uiText(13, c.textMuted, { padding: 14, lineHeight: 1.6 })}>
              PrusaLink printers have no config folder Farmhand can back up. Their settings stay on the printer.
            </div>
          ) : error ? (
            <div style={uiText(13, c.amber, { padding: 14 })}>Couldn't load the backups: {error}</div>
          ) : !data ? (
            <div style={uiText(13, c.textFaint, { padding: 14 })}>Loading…</div>
          ) : (
            <>
              <Schedule data={data} onSaved={load} onSsh={() => setDialog({ kind: "ssh" })} />
              {actionError && <div style={uiText(13, c.amber, { padding: "0 14px 10px", lineHeight: 1.5 })}>{actionError}</div>}
              {message && <div data-testid="backup-message" style={uiText(13, c.green, { padding: "0 14px 10px", lineHeight: 1.5 })}>{message}</div>}
              {backups.length === 0 ? (
                <div style={uiText(13, c.textMuted, { padding: "10px 14px 14px", borderTop: `1px solid ${c.border}` })}>No backups yet.</div>
              ) : (
                backups.map((b) => (
                  <div key={b.id} data-testid="backup-row" style={{ borderTop: `1px solid ${c.border}` }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 14px", flexWrap: "wrap" }}>
                      <button
                        onClick={() => setExpanded(expanded === b.id ? null : b.id)}
                        aria-expanded={expanded === b.id}
                        style={{ display: "flex", alignItems: "center", gap: 8, flex: "1 1 260px", minWidth: 0, border: "none", background: "none", padding: 0, cursor: "pointer", textAlign: "left", ...ui }}
                      >
                        <ChevronRight size={13} color={c.textMuted} style={{ transform: expanded === b.id ? "rotate(90deg)" : "none", flexShrink: 0 }} />
                        <span style={uiText(14, c.heading)}>{fmtWhen(b.taken_at)}</span>
                        <Badge tone={b.trigger === "automatic" ? "teal" : "muted"}>{TRIGGER[b.trigger] || b.trigger}</Badge>
                      </button>
                      <span title={changesHint(b.changes) || undefined} style={uiText(12, b.changes && changesText(b.changes) !== "no changes" ? c.amber : c.textFaint)}>
                        {changesText(b.changes)}
                      </span>
                      <span style={monoText(11, c.textFaint)}>
                        {plural(b.file_count, "file")} · {formatBytes(b.total_bytes)}
                      </span>
                      <div style={{ display: "flex", gap: 6 }}>
                        <a href={configBackupZipUrl(printer.id, b.id)} download style={{ ...headerButton(), textDecoration: "none" }} title="Download the whole backup as a zip">
                          <Download size={12} />
                          Zip
                        </a>
                        <button data-testid="backup-restore-all" onClick={() => setDialog({ kind: "restoreAll", backup: b })} style={headerButton()} title="Put this whole backup back on the printer">
                          <History size={12} />
                          Restore
                        </button>
                        {b.has_database && (
                          <button data-testid="backup-restore-database" onClick={() => setDialog({ kind: "restoreDb", backup: b })} style={headerButton()} title="Put Moonraker's whole database back as it was in this backup">
                            <Database size={12} />
                            Database
                          </button>
                        )}
                        <TrashButton title="Delete this backup (its files on the NAS too)" onClick={() => setDialog({ kind: "delete", backup: b })} />
                      </div>
                    </div>
                    {expanded === b.id && (
                      <BackupFiles
                        printer={printer}
                        backup={b}
                        onOpen={(file, mode) => setDialog({ kind: "file", backup: b, file, mode })}
                        onRestore={(file) => setDialog({ kind: "restore", backup: b, file })}
                      />
                    )}
                  </div>
                ))
              )}
            </>
          )}
        </div>
      )}

      {dialog?.kind === "file" && <FileDialog printer={printer} backup={dialog.backup} file={dialog.file} mode={dialog.mode} onClose={close} />}
      {dialog?.kind === "restore" && (
        <ConfirmDialog
          title="Put a file back on the printer"
          confirmLabel="Put it back"
          tone="warn"
          onClose={close}
          onConfirm={async () => {
            const d = await restoreConfigBackupFile(printer.id, dialog.backup.id, dialog.file.path);
            ask.current++;
            setData(d);
            setMessage(d.message);
            setActionError(null);
          }}
        >
          Put <b style={{ color: c.heading }}>{dialog.file.path}</b> back on {printer.name} as it was on {fmtWhen(dialog.backup.taken_at)}? It
          replaces the file there now. Farmhand first takes a backup of how things are, so this can be undone the same way.
          Klipper only reads it after a restart, which is left to you (Restart in {klipperUi(printer)}). Not while the printer is printing.
        </ConfirmDialog>
      )}
      {dialog?.kind === "restoreAll" && (
        <RestoreDialog
          printer={printer}
          backup={dialog.backup}
          onClose={close}
          onDone={(d) => {
            ask.current++;
            setData(d);
          }}
        />
      )}
      {dialog?.kind === "ssh" && <SshDialog printer={printer} onClose={close} onTested={load} />}
      {dialog?.kind === "restoreDb" && (
        <ConfirmDialog
          title="Restore Moonraker's database"
          confirmLabel="Restore database"
          tone="warn"
          onClose={close}
          onConfirm={async () => {
            const d = await restoreConfigBackupDatabase(printer.id, dialog.backup.id);
            ask.current++;
            setData(d);
            setMessage(d.message);
            setActionError(null);
          }}
        >
          Put Moonraker's whole database on {printer.name} back as it was on {fmtWhen(dialog.backup.taken_at)}? That's its print
          history, {klipperUi(printer)}'s settings, maintenance and everything else Moonraker keeps: anything newer in them is lost. Moonraker
          restarts itself afterwards and {klipperUi(printer)} reconnects in a few seconds. Farmhand first takes a backup of how things are now,
          so this can be undone the same way. Not while the printer is printing.
        </ConfirmDialog>
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title="Delete backup"
          onClose={close}
          onConfirm={async () => {
            const d = await deleteConfigBackup(printer.id, dialog.backup.id);
            ask.current++;
            setData(d);
          }}
        >
          Delete the backup of {fmtWhen(dialog.backup.taken_at)}? Its files are removed from the NAS. This can't be undone.
        </ConfirmDialog>
      )}
    </div>
  );
}
