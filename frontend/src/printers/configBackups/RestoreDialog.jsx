// Restore a whole backup: what it would change on the printer, then putting it back
import { useEffect, useState } from "react";
import { c } from "../../theme.js";
import { errorText, getConfigBackupRestorePreview, restoreConfigBackup } from "../../api.js";
import { cancelButton, monoText, primaryButton, uiText } from "../../styles.js";
import { Modal } from "../../components/common/dialogs.jsx";
import { fmtWhen, plural } from "../../lib/format.js";
import { klipperUi } from "../webUi.js";

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
export function RestoreDialog({ printer, backup, onClose, onDone }) {
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
                Klipper only reads its config after a restart, which is left to you (Restart in {klipperUi(printer)}). Not while the printer is printing.
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
