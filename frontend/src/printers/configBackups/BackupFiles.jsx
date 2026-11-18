// The files of one backup, opened under its row: view, changes, download and put back each one
import { useEffect, useState } from "react";
import { ChevronRight, Download, Eye, FileDiff, RotateCcw } from "lucide-react";
import { c, ui } from "../../theme.js";
import { configBackupFileUrl, errorText, getConfigBackup } from "../../api.js";
import { monoText, uiText } from "../../styles.js";
import { Badge } from "../../components/common/ui.jsx";
import { formatBytes, plural } from "../../lib/format.js";
import { smallButton } from "./shared.js";

export function BackupFiles({ printer, backup, onRestore, onOpen }) {
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
