import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight, Database, Download, Eye, FileDiff, History, KeyRound, RotateCcw, Save } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import {
  configBackupFileUrl,
  configBackupZipUrl,
  deleteConfigBackup,
  errorText,
  getConfigBackup,
  getConfigBackupDiff,
  getConfigBackupFile,
  getConfigBackupRestorePreview,
  getConfigBackups,
  getSshKey,
  restoreConfigBackup,
  restoreConfigBackupDatabase,
  restoreConfigBackupFile,
  setConfigBackupSchedule,
  takeConfigBackup,
  testSsh,
} from "../api.js";
import { cancelButton, fieldBox, foldHeading, headerButton, monoText, panelBox, primaryButton, uiText } from "../styles.js";
import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { Badge, SectionToggle, TrashButton } from "../components/common/ui.jsx";
import { formatBytes, fmtWhen, plural } from "../lib/format.js";

const TRIGGER = { manual: "by hand", automatic: "automatic", before_restore: "taken before a restore" };

// "2 changed, 1 added" since the backup before; the oldest kept has nothing to compare with
const changesText = (ch) => {
  if (!ch) return "the oldest kept";
  const parts = [["changed", ch.changed], ["added", ch.added], ["removed", ch.removed]].filter(([, l]) => l.length).map(([w, l]) => `${l.length} ${w}`);
  return parts.length ? parts.join(", ") : "no changes";
};
const changesHint = (ch) =>
  ch && [["Changed", ch.changed], ["Added", ch.added], ["Removed", ch.removed]].filter(([, l]) => l.length).map(([w, l]) => `${w}: ${l.join(", ")}`).join("\n");

const smallButton = { ...headerButton(), padding: "3px 8px", fontSize: fs(11) };
const iconButton = { ...headerButton(), padding: 0, width: 26, justifyContent: "center" };

// A file as text, or a diff with its added and removed lines marked
function TextView({ text, diff }) {
  const lines = (text ?? "").split("\n");
  return (
    <pre style={{ ...monoText(12, c.text), margin: 0, maxHeight: "65vh", overflow: "auto", background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 3, padding: 10, whiteSpace: "pre" }}>
      {lines.map((l, i) => {
        const color = !diff ? undefined : l.startsWith("+") && !l.startsWith("+++") ? c.green : l.startsWith("-") && !l.startsWith("---") ? c.danger : l.startsWith("@@") ? c.teal : c.textMuted;
        return (
          <div key={i} style={{ color }}>
            {l || " "}
          </div>
        );
      })}
    </pre>
  );
}

function FileDialog({ printer, backup, file, mode, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const ask = mode === "diff" ? getConfigBackupDiff : getConfigBackupFile;
    ask(printer.id, backup.id, file.path).then(setData, (e) => setError(errorText(e)));
  }, []);
  let body;
  if (error) body = <div style={uiText(13, c.amber)}>{error}</div>;
  else if (!data) body = <div style={uiText(13, c.textFaint)}>Loading…</div>;
  else if (data.binary) body = <div style={uiText(13, c.textMuted)}>This file isn't text, so it can't be shown here. Download it instead.</div>;
  else if (mode === "diff" && data.change === "same") body = <div style={uiText(13, c.textMuted)}>No changes since the backup of {fmtWhen(data.previous_taken_at)}.</div>;
  else if (mode === "diff") {
    body = (
      <>
        <div style={uiText(12, c.textMuted, { marginBottom: 8 })}>
          {data.change === "added" ? "New in this backup" : "Changes"} since the backup of {fmtWhen(data.previous_taken_at)}.
        </div>
        <TextView text={data.diff} diff />
      </>
    );
  } else body = <TextView text={data.text} />;
  return (
    <Modal title={`${file.path} · ${fmtWhen(backup.taken_at)}`} onClose={onClose} width={900}>
      {body}
    </Modal>
  );
}

function BackupFiles({ printer, backup, onRestore, onOpen }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [showSkipped, setShowSkipped] = useState(false);
  useEffect(() => {
    getConfigBackup(printer.id, backup.id).then(setDetail, (e) => setError(errorText(e)));
  }, [backup.id]);
  if (error) return <div style={uiText(12, c.amber, { padding: "8px 14px 10px 34px" })}>{error}</div>;
  if (!detail) return <div style={uiText(12, c.textFaint, { padding: "8px 14px 10px 34px" })}>Loading…</div>;
  const config = detail.files.filter((f) => !f.database);
  const database = detail.files.filter((f) => f.database);
  const row = (f) => (
    <div key={f.path} data-testid="backup-file" style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 14px 5px 34px", flexWrap: "wrap" }}>
      <span style={monoText(12, c.text, { flex: "1 1 220px", minWidth: 0, overflowWrap: "anywhere" })}>{f.path}</span>
      {f.change === "added" && <Badge tone="green">added</Badge>}
      {f.change === "changed" && <Badge tone="amber">changed</Badge>}
      <span style={monoText(11, c.textFaint, { width: 60, textAlign: "right" })}>{formatBytes(f.size)}</span>
      <div style={{ display: "flex", gap: 6 }}>
        <button onClick={() => onOpen(f, "view")} style={smallButton} title="Show this file">
          <Eye size={11} />
          View
        </button>
        {f.change && f.change !== "same" && (
          <button onClick={() => onOpen(f, "diff")} style={smallButton} title="What changed since the backup before">
            <FileDiff size={11} />
            Changes
          </button>
        )}
        <a href={configBackupFileUrl(printer.id, backup.id, f.path)} download style={{ ...smallButton, textDecoration: "none" }} title="Download this file">
          <Download size={11} />
        </a>
        {!f.database && (
          <button data-testid="backup-restore" onClick={() => onRestore(f)} style={smallButton} title="Put this file back on the printer as it is in this backup">
            <RotateCcw size={11} />
            Put back
          </button>
        )}
      </div>
    </div>
  );
  return (
    <div style={{ paddingBottom: 8 }}>
      <div style={uiText(11, c.textFaint, { padding: "6px 14px 2px 34px" })}>Config folder</div>
      {config.map(row)}
      {database.length > 0 && <div style={uiText(11, c.textFaint, { padding: "8px 14px 2px 34px" })}>From Moonraker's database (print history, Mainsail's settings, maintenance…)</div>}
      {database.map(row)}
      {detail.changes?.removed.length > 0 && (
        <div style={uiText(12, c.textMuted, { padding: "6px 14px 0 34px" })}>Gone since the backup before: {detail.changes.removed.join(", ")}</div>
      )}
      {detail.skipped.length > 0 && (
        <div style={{ padding: "6px 14px 0 34px" }}>
          <button onClick={() => setShowSkipped(!showSkipped)} style={{ display: "flex", alignItems: "center", gap: 6, border: "none", background: "none", padding: 0, cursor: "pointer", ...uiText(12, c.textFaint) }}>
            <ChevronRight size={12} style={{ transform: showSkipped ? "rotate(90deg)" : "none" }} />
            {plural(detail.skipped.length, "file")} left out (Klipper's old copies, backups, results, pictures, archives)
          </button>
          {showSkipped && (
            <div style={{ marginTop: 4, maxHeight: 240, overflow: "auto" }}>
              {detail.skipped.map((s) => (
                <div key={s.path} style={monoText(11, c.textFaint, { padding: "1px 0 1px 18px", overflowWrap: "anywhere" })}>
                  {s.path} <span style={{ ...ui }}>— {s.reason}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// A list of paths under a heading, kept short: the first few, then how many more
function PathList({ title, paths, tone = c.textMuted }) {
  const [all, setAll] = useState(false);
  if (!paths.length) return null;
  const shown = all ? paths : paths.slice(0, 8);
  return (
    <div style={{ marginTop: 10 }}>
      <div style={uiText(12, c.textMuted, { marginBottom: 3 })}>{title}</div>
      {shown.map((p) => (
        <div key={p} style={monoText(12, tone, { paddingLeft: 10, overflowWrap: "anywhere" })}>
          {p}
        </div>
      ))}
      {paths.length > shown.length && (
        <button onClick={() => setAll(true)} style={{ border: "none", background: "none", padding: "2px 10px", cursor: "pointer", ...uiText(12, c.teal) }}>
          and {paths.length - shown.length} more…
        </button>
      )}
    </div>
  );
}

// Restore: first what it would change (read from the printer, nothing written), then, on Restore, the whole backup back
function RestoreDialog({ printer, backup, onClose, onDone }) {
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  useEffect(() => {
    getConfigBackupRestorePreview(printer.id, backup.id).then(setPlan, (e) => setError(errorText(e)));
  }, []);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const d = await restoreConfigBackup(printer.id, backup.id);
      setResult(d);
      onDone(d);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const settingsKeys = plan ? plan.settings.reduce((n, s) => n + s.keys.length, 0) : 0;
  const overSsh = plan ? (plan.files.over_ssh || []).length : 0;
  const nothing = plan && plan.files.put_back.length === 0 && overSsh === 0 && settingsKeys === 0;
  return (
    <Modal title={`Restore ${printer.name} to ${fmtWhen(backup.taken_at)}`} onClose={busy ? () => {} : onClose} width={620} closeOnBackdrop={!busy}>
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6 })}>
        {result ? (
          <>
            <div data-testid="restore-result" style={{ color: result.failed.length ? c.amber : c.green }}>{result.message}</div>
            {result.failed.map((f) => (
              <div key={f.path} style={uiText(12, c.amber, { marginTop: 4 })}>
                <span style={monoText(12, c.amber)}>{f.path}</span>: {f.error}
              </div>
            ))}
          </>
        ) : !plan && !error ? (
          <div style={{ color: c.textFaint }}>Comparing the backup with the printer…</div>
        ) : plan ? (
          <>
            {nothing ? (
              <div>{printer.name} is already as it was in this backup: nothing would change.</div>
            ) : (
              <div>
                Restore puts {[plan.files.put_back.length + overSsh && plural(plan.files.put_back.length + overSsh, "config file"), settingsKeys && plural(settingsKeys, "Moonraker setting")].filter(Boolean).join(" and ")} back
                on {printer.name} as {plan.files.put_back.length + overSsh + settingsKeys === 1 ? "it was" : "they were"} in this backup ({plural(plan.files.same, "file")} already the same).
                Nothing is deleted. Farmhand first takes a backup of how things are now, so this can be undone by restoring that one.
                Klipper only reads its config after a restart, which is left to you (Restart in Mainsail). Not while the printer is printing.
              </div>
            )}
            <PathList title="Config files put back" paths={plan.files.put_back} tone={c.text} />
            <PathList title="Read-only to Moonraker, written where they really are over SSH (the link stays)" paths={plan.files.over_ssh || []} tone={c.text} />
            <PathList title="Moonraker settings put back" paths={plan.settings.map((s) => `${s.namespace}: ${s.keys.join(", ")}`)} tone={c.text} />
            <PathList title="Left as they are (read-only on the printer: set up SSH to put them back)" paths={plan.files.read_only} />
            <PathList title="On the printer but not in this backup (left as they are)" paths={plan.left_alone} />
            <div style={uiText(12, c.textFaint, { marginTop: 10 })}>
              Moonraker's print history isn't part of this: {backup.has_database ? "Restore database puts back Moonraker's whole database, history included." : "this backup has no copy of Moonraker's database (SSH wasn't set up)."}
            </div>
          </>
        ) : null}
        {error && <div style={uiText(13, c.amber, { marginTop: 10 })}>{error}</div>}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
        <button onClick={onClose} disabled={busy} style={cancelButton(busy)}>
          {result ? "Close" : "Cancel"}
        </button>
        {!result && plan && !nothing && (
          <button data-testid="restore-confirm" onClick={run} disabled={busy} style={primaryButton(busy)}>
            {busy ? "Restoring…" : "Restore"}
          </button>
        )}
      </div>
    </Modal>
  );
}

// Set up SSH: Farmhand's key, how to add it on the printer's Pi, and a test
function SshDialog({ printer, onClose, onTested }) {
  const [key, setKey] = useState(null);
  const [error, setError] = useState(null);
  const [test, setTest] = useState(null);
  const [testing, setTesting] = useState(false);
  useEffect(() => {
    getSshKey().then(setKey, (e) => setError(errorText(e)));
  }, []);
  const runTest = async () => {
    setTesting(true);
    try {
      setTest(await testSsh(printer.id));
      onTested(); // the section's "Tested" follows the answer
    } catch (e) {
      setTest({ ok: false, error: errorText(e) });
    } finally {
      setTesting(false);
    }
  };
  const command = key ? `mkdir -p ~/.ssh && echo '${key}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys` : "";
  return (
    <Modal title={`Set up SSH for ${printer.name}`} onClose={onClose} width={640}>
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6 })}>
        With SSH, each backup also holds Moonraker's database file (print history, Mainsail's settings, maintenance:
        everything), which Restore database can put back, and Restore can put back mainsail.cfg. Farmhand logs in with
        its own key, never a password. Add the key once on {printer.name}'s Pi: log in to it (as the user Klipper runs as,
        usually pi) and run:
      </div>
      {error && <div style={uiText(13, c.amber, { marginTop: 10 })}>{error}</div>}
      {key && (
        <pre data-testid="ssh-command" style={{ ...monoText(12, c.text), marginTop: 10, padding: 10, background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 3, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {command}
        </pre>
      )}
      {test && (
        <div data-testid="ssh-test-result" style={uiText(13, test.ok ? c.green : c.amber, { marginTop: 10, lineHeight: 1.5 })}>
          {test.ok ? `Farmhand can log in to ${printer.name} as ${test.user} (${test.host}).` : test.error}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
        <button onClick={onClose} style={cancelButton(false)}>
          Close
        </button>
        <button data-testid="ssh-test" onClick={runTest} disabled={testing} style={primaryButton(testing)}>
          {testing ? "Testing…" : "Test SSH"}
        </button>
      </div>
    </Modal>
  );
}

function Schedule({ data, onSaved, onSsh }) {
  const [days, setDays] = useState(String(data.every_days));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setDays(String(data.every_days)), [data.every_days]);
  const n = Number(days);
  const valid = days.trim() !== "" && Number.isInteger(n) && n >= 0 && n <= 365;
  const save = async () => {
    setBusy(true);
    try {
      await setConfigBackupSchedule(n);
      setError(null);
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", ...uiText(13, c.textMuted) }}>
        <span>Back up every printer automatically every</span>
        <input
          data-testid="backup-every-days"
          type="number"
          min={0}
          max={365}
          value={days}
          onChange={(e) => setDays(e.target.value)}
          aria-label="Days between automatic backups"
          style={{ ...fieldBox(), width: 70, padding: "4px 8px" }}
        />
        <span>days (0 = never).</span>
        {valid && n !== data.every_days && (
          <button onClick={save} disabled={busy} style={smallButton}>
            <Save size={11} />
            {busy ? "Saving…" : "Save"}
          </button>
        )}
        {data.every_days > 0 && data.next_due_at && <span style={{ color: c.textFaint }}>Next one for this printer: {new Date(data.next_due_at) <= new Date() ? "at the next sync" : fmtWhen(data.next_due_at)}</span>}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", ...uiText(12, c.textFaint) }}>
        <span>{data.ssh ? "Moonraker's database file is copied into each backup over SSH." : "Moonraker's database file is only in backups when SSH to the printer is set up."}</span>
        <button data-testid="ssh-setup" onClick={onSsh} style={smallButton}>
          <KeyRound size={11} />
          Set up SSH
        </button>
        {data.ssh && (
          <span
            data-testid="ssh-tested"
            title={`Farmhand logged in as ${data.ssh.user}@${data.ssh.host} on ${fmtWhen(data.ssh.tested_at)}`}
            style={{ display: "inline-flex", alignItems: "center", gap: 4, color: c.green, fontWeight: 600 }}
          >
            <Check size={12} />
            Tested
          </span>
        )}
      </div>
      <div style={uiText(12, c.textFaint, { lineHeight: 1.5 })}>
        Each backup holds the printer's config folder and what its Moonraker keeps in its database (the whole print history,
        Mainsail's settings, maintenance). The newest {data.keep} are kept, in <span style={monoText(12, c.textMuted)}>{data.folder}</span> (the
        printer backups folder: change it on the Settings page). Never taken while the printer is printing.
      </div>
      {error && <div style={uiText(12, c.amber)}>{error}</div>}
    </div>
  );
}

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
          Klipper only reads it after a restart, which is left to you (Restart in Mainsail). Not while the printer is printing.
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
          history, Mainsail's settings, maintenance and everything else Moonraker keeps: anything newer in them is lost. Moonraker
          restarts itself afterwards and Mainsail reconnects in a few seconds. Farmhand first takes a backup of how things are now,
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
