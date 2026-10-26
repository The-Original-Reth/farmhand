import { useState } from "react";
import { X } from "lucide-react";
import { c, fs, ui } from "../../theme.js";
import { errorText } from "../../api.js";
import { cancelButton, primaryButton, uiText } from "../../styles.js";

// Every destructive action goes through this: say exactly what will happen,
// then do it only on an explicit second click.
export function ConfirmDialog({ title, confirmLabel = "Delete", tone = "danger", onConfirm, onClose, children }) {
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const run = async () => {
    setSubmitting(true);
    setErrorMsg(null);
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      setErrorMsg(errorText(e));
      setSubmitting(false);
    }
  };

  return (
    <Modal title={title} onClose={submitting ? () => {} : onClose} width={480}>
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 14 })}>{children}</div>
      {errorMsg && (
        <div style={uiText(12, tone === "danger" ? c.danger : c.amber, { marginBottom: 10, lineHeight: 1.5 })}>{errorMsg}</div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button
          onClick={onClose}
          disabled={submitting}
          style={cancelButton(submitting)}
        >
          Cancel
        </button>
        <button
          onClick={run}
          disabled={submitting}
          style={{ ...ui, fontSize: fs(13), background: tone === "danger" ? c.danger : c.amber, color: tone === "danger" ? c.onDanger : c.onAccent, border: "none", borderRadius: 3, padding: "7px 14px", fontWeight: 600, cursor: submitting ? "default" : "pointer", opacity: submitting ? 0.7 : 1 }}
        >
          {submitting ? (tone === "danger" ? "Deleting…" : "Working…") : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

export function DeleteWarning({ children }) {
  return <div style={{ color: c.amber, marginTop: 8 }}>{children}</div>;
}

// ---------------------------------------------------------------------------
// Models section
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Upload — real, wired to the API. STL/OBJ/STEP go to the library; a 3MF
// needs a source model + a printer (auto-detected from the file). gcode
// is optional — it doesn't have to be on hand at upload time.
// ---------------------------------------------------------------------------
export function Modal({ title, onClose, children, width = 420 }) {
  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width,
          maxWidth: "90vw",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          background: c.panel,
          border: `1px solid ${c.borderStrong}`,
          borderRadius: 6,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 16px",
            borderBottom: `1px solid ${c.border}`,
            flexShrink: 0,
          }}
        >
          <div style={uiText(14, c.heading, { fontWeight: 600 })}>{title}</div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: c.textFaint, cursor: "pointer", padding: 2 }}
          >
            <X size={16} />
          </button>
        </div>
        <div style={{ padding: 16, overflow: "auto" }}>{children}</div>
      </div>
    </div>
  );
}

export function ModalActions({ onClose, onSubmit, actionLabel, submitting, errorMsg, submittingLabel = "Uploading…" }) {
  return (
    <div>
      {errorMsg && (
        <div style={uiText(12, c.amber, { marginBottom: 10, lineHeight: 1.5 })}>{errorMsg}</div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
        <button
          onClick={onClose}
          disabled={submitting}
          style={cancelButton(submitting)}
        >
          Cancel
        </button>
        <button
          onClick={onSubmit}
          disabled={submitting}
          style={primaryButton(submitting)}
        >
          {submitting ? submittingLabel : actionLabel}
        </button>
      </div>
    </div>
  );
}
