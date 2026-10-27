import { useState } from "react";
import { c, fs, ui } from "../theme.js";
import { uiText } from "../styles.js";
import { createPrinter, errorText, updatePrinter } from "../api.js";
import { useData } from "../data.jsx";

import { ModalActions } from "../components/common/dialogs.jsx";
import { FieldSelect, TextField } from "../components/common/fields.jsx";

// How Farmhand reaches a printer, as both printer forms ask it. conn: { type: "moonraker" | "prusalink", moonrakerUrl,
// apiKey, removeKey, prusalinkUrl, prusalinkUsername, prusalinkPassword }. saved: the printer as it is (Edit), for
// saying a key or password is already saved; null when adding. ip: the IP typed above, for the default addresses.
const CONNECTIONS = [
  { value: "moonraker", label: "Mainsail (Moonraker / Klipper: Voron...)" },
  { value: "prusalink", label: "PrusaLink (Prusa Core One, MK4, XL...)" },
];
const newConnection = (printer = null) => ({
  type: printer?.connectionType || "moonraker",
  moonrakerUrl: printer?.moonrakerUrlOverride || "",
  apiKey: "", // blank = keep whatever is saved
  removeKey: false,
  prusalinkUrl: printer?.prusalinkUrlOverride || "",
  prusalinkUsername: printer?.prusalinkUsername || "maker",
  prusalinkPassword: "", // blank = keep whatever is saved
});
// What the API is sent for it: only the chosen kind's fields
const connectionFields = (conn) =>
  conn.type === "prusalink"
    ? {
        connectionType: "prusalink",
        prusalinkUrl: conn.prusalinkUrl.trim(),
        prusalinkUsername: conn.prusalinkUsername.trim() || "maker",
        prusalinkPassword: conn.prusalinkPassword || undefined,
      }
    : { connectionType: "moonraker", moonrakerUrl: conn.moonrakerUrl.trim(), moonrakerApiKey: conn.removeKey ? "" : conn.apiKey.trim() || undefined };

function ConnectionFields({ conn, setConn, ip, saved = null }) {
  const set = (key) => (value) => setConn((c) => ({ ...c, [key]: value }));
  return (
    <>
      <FieldSelect label="Connection" value={conn.type} onChange={set("type")} options={CONNECTIONS} />
      {conn.type === "prusalink" ? (
        <>
          <TextField
            label="PrusaLink address (optional)"
            value={conn.prusalinkUrl}
            onChange={set("prusalinkUrl")}
            placeholder={ip ? `Leave blank to use http://${ip}` : "Add an IP above, or give the address here"}
          />
          <TextField label="PrusaLink username" value={conn.prusalinkUsername} onChange={set("prusalinkUsername")} placeholder="maker" />
          <TextField
            label="PrusaLink password"
            type="password"
            value={conn.prusalinkPassword}
            onChange={set("prusalinkPassword")}
            placeholder={saved?.hasPrusalinkPassword ? "A password is saved. Type a new one to replace it." : "Shown on the printer: Settings > Network > PrusaLink"}
          />
        </>
      ) : (
        <>
          <TextField
            label="Moonraker address (optional)"
            value={conn.moonrakerUrl}
            onChange={set("moonrakerUrl")}
            placeholder={ip ? `Leave blank to use http://${ip}:7125` : "Add an IP above, or give the address here"}
          />
          <TextField
            label="Moonraker API key (optional)"
            type="password"
            value={conn.apiKey}
            onChange={(v) => setConn((c) => ({ ...c, apiKey: v, removeKey: v ? false : c.removeKey }))}
            disabled={conn.removeKey}
            placeholder={saved?.hasMoonrakerApiKey ? "A key is saved. Type a new one to replace it." : "Only needed if Moonraker asks for one"}
          />
          {saved?.hasMoonrakerApiKey && (
            <label style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(13), color: c.textMuted, marginTop: -6, marginBottom: 14, cursor: "pointer" }}>
              <input type="checkbox" checked={conn.removeKey} onChange={(e) => set("removeKey")(e.target.checked)} style={{ accentColor: c.amber }} />
              Remove the saved API key
            </label>
          )}
        </>
      )}
    </>
  );
}

export function AddPrinterForm({ onClose }) {
  const { putPrinter } = useData();
  const [name, setName] = useState("");
  const [kind, setKind] = useState("");
  const [wiredIp, setWiredIp] = useState("");
  const [wirelessIp, setWirelessIp] = useState("");
  const [conn, setConn] = useState(() => newConnection());
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!name.trim()) return setErrorMsg("A printer needs a name.");
    setSubmitting(true);
    try {
      putPrinter(await createPrinter({ name: name.trim(), kind: kind.trim(), wiredIp: wiredIp.trim(), wirelessIp: wirelessIp.trim(), ...connectionFields(conn) }));
      onClose();
    } catch (e) {
      setErrorMsg(errorText(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="Must match the printer profile name inside your 3MF files exactly" />
      <TextField label="Type (optional)" value={kind} onChange={setKind} placeholder="e.g. Prusa Core One" />
      <TextField label="Wired IP (optional)" value={wiredIp} onChange={setWiredIp} placeholder="e.g. 10.0.6.21" />
      <TextField label="Wireless IP (optional)" value={wirelessIp} onChange={setWirelessIp} placeholder="e.g. 10.0.6.121" />
      <ConnectionFields conn={conn} setConn={setConn} ip={wiredIp.trim() || wirelessIp.trim()} />
      <div style={uiText(11, c.textFaint, { marginBottom: 14, lineHeight: 1.5 })}>
        The name is the printer's unique key, and it's what a 3MF upload is matched against — it has to be spelled exactly like the printer profile your slicer put in the file (including capitalization and spaces).
      </div>
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel="Add printer" submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}

export function EditPrinterForm({ printer, onClose }) {
  const { putPrinter, bundlesForPrinter } = useData();
  const [name, setName] = useState(printer.name);
  const [kind, setKind] = useState(printer.kind || "");
  const [wiredIp, setWiredIp] = useState(printer.wired || "");
  const [wirelessIp, setWirelessIp] = useState(printer.wireless || "");
  const [decommissioned, setDecommissioned] = useState(!!printer.decommissioned);
  const [conn, setConn] = useState(() => newConnection(printer));
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const hasFiles = bundlesForPrinter(printer.id).length > 0;

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!name.trim()) return setErrorMsg("A printer needs a name.");
    setSubmitting(true);
    try {
      putPrinter(await updatePrinter(printer.id, {
        name: name.trim(),
        kind: kind.trim(),
        wiredIp: wiredIp.trim(),
        wirelessIp: wirelessIp.trim(),
        decommissioned,
        ...connectionFields(conn),
      }));
      onClose();
    } catch (e) {
      setErrorMsg(errorText(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="Unique printer name" />
      <TextField label="Type" value={kind} onChange={setKind} placeholder="e.g. Prusa Core One" />
      <TextField label="Wired IP" value={wiredIp} onChange={setWiredIp} placeholder="e.g. 10.0.6.21" />
      <TextField label="Wireless IP" value={wirelessIp} onChange={setWirelessIp} placeholder="e.g. 10.0.6.121" />
      <ConnectionFields conn={conn} setConn={setConn} ip={wiredIp.trim() || wirelessIp.trim()} saved={printer} />
      <label style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(13), color: c.textMuted, marginBottom: 14, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={decommissioned}
          onChange={(e) => setDecommissioned(e.target.checked)}
          style={{ accentColor: c.amber }}
        />
        Decommissioned (retired — kept for its history, but not offered for new uploads)
      </label>
      {hasFiles && name.trim() !== printer.name && (
        <div style={uiText(11, c.textFaint, { marginBottom: 14, lineHeight: 1.5 })}>
          Renaming is safe for the files already here: they stay locked to this printer, and files sliced under the old
          name will still be matched to it.
        </div>
      )}
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel="Save" submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}
