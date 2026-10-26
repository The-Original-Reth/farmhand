import { useState } from "react";
import { FileCode, Send } from "lucide-react";
import { c } from "../theme.js";
import { bundleGcodeUrl, sendGcode } from "../api.js";
import { headerButton, monoText, uiText } from "../styles.js";
import { useData } from "../data.jsx";

import { ConfirmDialog } from "../components/common/dialogs.jsx";
import { DownloadButton } from "../components/common/ui.jsx";

// A 3MF version's G-code, on a line under the version: its name, Download, and Send to the printer the 3MF was
// sliced for (asked first: it starts printing straight away)
export function GcodeRow({ ver, bundle }) {
  const { printers } = useData();
  const printer = printers.find((p) => p.id === bundle.printerId);
  const [confirming, setConfirming] = useState(false);
  const [sent, setSent] = useState(null); // what the printer was sent, once it was

  return (
    <div
      data-testid="gcode-row"
      data-version={ver.v}
      style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 16px 9px 128px", flexWrap: "wrap" }}
    >
      <FileCode size={13} color={c.textFaint} />
      <span style={uiText(12, c.textFaint)}>G-code</span>
      <span style={monoText(12, c.textPrimary, { minWidth: 0, overflowWrap: "anywhere" })}>{ver.gcodeName}</span>
      {sent && (
        <span data-testid="gcode-sent" style={uiText(12, c.green)}>
          Sent to {sent.printer} and started
        </span>
      )}
      <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
        <DownloadButton href={bundleGcodeUrl(ver.id)} />
        {printer && (
          <button
            data-testid="gcode-send"
            onClick={() => setConfirming(true)}
            title={`Send this G-code to ${printer.name} and start printing it`}
            style={headerButton()}
          >
            <Send size={12} />
            Send to {printer.name}
          </button>
        )}
      </div>
      {confirming && (
        <ConfirmDialog
          title="Send to printer"
          confirmLabel="Send and print"
          tone="amber"
          onClose={() => setConfirming(false)}
          onConfirm={async () => setSent(await sendGcode(ver.id))}
        >
          Send <b style={{ color: c.heading }}>{ver.gcodeName}</b> to <b style={{ color: c.heading }}>{printer.name}</b> and
          start printing it now? Make sure the bed is clear and the right filament is loaded. A file of the same name on
          the printer is replaced.
        </ConfirmDialog>
      )}
    </div>
  );
}
