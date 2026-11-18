// The top of the Backups section: how often backups are taken, SSH, and where they are kept
import { useEffect, useState } from "react";
import { Check, KeyRound, Save } from "lucide-react";
import { c } from "../../theme.js";
import { errorText, setConfigBackupSchedule } from "../../api.js";
import { fieldBox, monoText, uiText } from "../../styles.js";
import { fmtWhen } from "../../lib/format.js";
import { smallButton } from "./shared.js";

export function Schedule({ data, onSaved, onSsh }) {
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
