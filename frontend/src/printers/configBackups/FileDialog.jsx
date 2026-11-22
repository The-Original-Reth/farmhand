// One file of a backup, shown as text or as what changed since the backup before
import { c } from "../../theme.js";
import { getConfigBackupDiff, getConfigBackupFile } from "../../api.js";
import { useLoad } from "../../hooks/useLoad.js";
import { monoText, uiText } from "../../styles.js";
import { Modal } from "../../components/common/dialogs.jsx";
import { fmtWhen } from "../../lib/format.js";

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

export function FileDialog({ printer, backup, file, mode, onClose }) {
  const { data, error } = useLoad(() => (mode === "diff" ? getConfigBackupDiff : getConfigBackupFile)(printer.id, backup.id, file.path), []);
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
