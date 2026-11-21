// Setting up SSH to a printer, so its backups also hold Moonraker's database
import { useEffect, useState } from "react";
import { c } from "../../theme.js";
import { errorText, getSshKey, testSsh } from "../../api.js";
import { cancelButton, monoText, primaryButton, uiText } from "../../styles.js";
import { Modal } from "../../components/common/dialogs.jsx";
import { klipperUi } from "../webUi.js";

// Set up SSH: Farmhand's key, how to add it on the printer's Pi, and a test
export function SshDialog({ printer, onClose, onTested }) {
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
        With SSH, each backup also holds Moonraker's database file (print history, {klipperUi(printer)}'s settings, maintenance:
        everything), which Restore database can put back, and Restore can put back {klipperUi(printer) === "Fluidd" ? "fluidd.cfg" : "mainsail.cfg"}. Farmhand logs in with
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
