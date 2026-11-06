import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { fieldBox, toolButton, uiText } from "../styles.js";
import { createPrinter, errorText, getPrusaLinkPassword, updatePrinter } from "../api.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";

import { ModalActions } from "../components/common/dialogs.jsx";
import { FieldSelect, TextField } from "../components/common/fields.jsx";

// How Farmhand reaches a printer, as both printer forms ask it. conn: { type: "moonraker" | "prusalink", moonrakerUrl,
// apiKey, removeKey, prusalinkUrl, prusalinkUsername, prusalinkPassword, cameraAddress }. saved: the printer as it is (Edit), for
// saying a key or password is already saved; null when adding. ips: the wired and wireless IPs typed above (either may be
// blank), for the default addresses: Moonraker and PrusaLink are each tried at both, wired first.
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
  cameraAddress: printer?.cameraAddress || "", // the Buddy3D camera's IP: a Prusa's camera has its own
});
// The PrusaLink password box, with Show / Hide. Showing it on a printer with one saved fetches the saved one into the box
// (saving the form then keeps it as it is).
function PrusaLinkPassword({ value, onChange, saved }) {
  const [shown, setShown] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const toggle = async () => {
    setError(null);
    if (!shown && !value && saved?.hasPrusalinkPassword) {
      setLoading(true);
      try {
        onChange((await getPrusaLinkPassword(saved.id)) || "");
      } catch (e) {
        setLoading(false);
        return setError(`Couldn't fetch the saved password: ${errorText(e)}`);
      }
      setLoading(false);
    }
    setShown(!shown);
  };
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={uiText(12, c.textFaint, { marginBottom: 5 })}>PrusaLink password</div>
      <div style={{ display: "flex", gap: 6 }}>
        <input
          data-testid="prusalink-password"
          type={shown ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={saved?.hasPrusalinkPassword ? "A password is saved. Type a new one to replace it, or Show it." : "Shown on the printer: Settings > Network > PrusaLink"}
          autoComplete="new-password"
          aria-label="PrusaLink password"
          style={{ ...fieldBox(), flex: 1, minWidth: 0, padding: "8px 10px", fontSize: fs(13), ...ui }}
        />
        <button
          type="button"
          data-testid="prusalink-password-show"
          onClick={toggle}
          disabled={loading}
          title={shown ? "Hide the password" : saved?.hasPrusalinkPassword && !value ? "Show the saved password" : "Show the password"}
          style={toolButton(12, { whiteSpace: "nowrap" })}
        >
          {shown ? <EyeOff size={13} /> : <Eye size={13} />}
          {loading ? "Fetching…" : shown ? "Hide" : "Show"}
        </button>
      </div>
      {error && <div style={uiText(12, c.amber, { marginTop: 5 })}>{error}</div>}
    </div>
  );
}

// What the API is sent for it: only the chosen kind's fields
const connectionFields = (conn) =>
  conn.type === "prusalink"
    ? {
        connectionType: "prusalink",
        prusalinkUrl: conn.prusalinkUrl.trim(),
        prusalinkUsername: conn.prusalinkUsername.trim() || "maker",
        prusalinkPassword: conn.prusalinkPassword || undefined,
        cameraAddress: conn.cameraAddress.trim(),
      }
    : { connectionType: "moonraker", moonrakerUrl: conn.moonrakerUrl.trim(), moonrakerApiKey: conn.removeKey ? "" : conn.apiKey.trim() || undefined };

function ConnectionFields({ conn, setConn, ips, saved = null }) {
  const set = (key) => (value) => setConn((c) => ({ ...c, [key]: value }));
  const [ip, otherIp] = ips.filter(Boolean);
  const both = otherIp && otherIp !== ip;
  return (
    <>
      <FieldSelect label="Connection" value={conn.type} onChange={set("type")} options={CONNECTIONS} />
      {conn.type === "prusalink" ? (
        <>
          <TextField
            label="PrusaLink address (optional)"
            value={conn.prusalinkUrl}
            onChange={set("prusalinkUrl")}
            placeholder={
              !ip ? "Add an IP above, or give the address here"
                : both ? `Leave blank to use http://${ip}, or http://${otherIp} when that doesn't answer`
                  : `Leave blank to use http://${ip}`
            }
          />
          <TextField label="PrusaLink username" value={conn.prusalinkUsername} onChange={set("prusalinkUsername")} placeholder="maker" />
          <PrusaLinkPassword value={conn.prusalinkPassword} onChange={set("prusalinkPassword")} saved={saved} />
          <TextField
            label="Buddy3D camera IP (optional)"
            value={conn.cameraAddress}
            onChange={set("cameraAddress")}
            placeholder="e.g. 192.168.10.131. Turn on local streaming for it in the Prusa app"
          />
        </>
      ) : (
        <>
          <TextField
            label="Moonraker address (optional)"
            value={conn.moonrakerUrl}
            onChange={set("moonrakerUrl")}
            placeholder={
              !ip ? "Add an IP above, or give the address here"
                : both ? `Leave blank to use http://${ip}:7125, or http://${otherIp}:7125 when that doesn't answer`
                  : `Leave blank to use http://${ip}:7125`
            }
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
  const { busy: submitting, error: errorMsg, setError: setErrorMsg, run } = useAction();

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!name.trim()) return setErrorMsg("A printer needs a name.");
    await run(async () => {
      putPrinter(await createPrinter({ name: name.trim(), kind: kind.trim(), wiredIp: wiredIp.trim(), wirelessIp: wirelessIp.trim(), ...connectionFields(conn) }));
      onClose();
    });
  };

  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="Must match the printer profile name inside your 3MF files exactly" />
      <TextField label="Type (optional)" value={kind} onChange={setKind} placeholder="e.g. Prusa Core One" />
      <TextField label="Wired IP (optional)" value={wiredIp} onChange={setWiredIp} placeholder="e.g. 10.0.6.21" />
      <TextField label="Wireless IP (optional)" value={wirelessIp} onChange={setWirelessIp} placeholder="e.g. 10.0.6.121" />
      <ConnectionFields conn={conn} setConn={setConn} ips={[wiredIp.trim(), wirelessIp.trim()]} />
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
  const { busy: submitting, error: errorMsg, setError: setErrorMsg, run } = useAction();
  const hasFiles = bundlesForPrinter(printer.id).length > 0;

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!name.trim()) return setErrorMsg("A printer needs a name.");
    await run(async () => {
      putPrinter(await updatePrinter(printer.id, {
        name: name.trim(),
        kind: kind.trim(),
        wiredIp: wiredIp.trim(),
        wirelessIp: wirelessIp.trim(),
        decommissioned,
        ...connectionFields(conn),
      }));
      onClose();
    });
  };

  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="Unique printer name" />
      <TextField label="Type" value={kind} onChange={setKind} placeholder="e.g. Prusa Core One" />
      <TextField label="Wired IP" value={wiredIp} onChange={setWiredIp} placeholder="e.g. 10.0.6.21" />
      <TextField label="Wireless IP" value={wirelessIp} onChange={setWirelessIp} placeholder="e.g. 10.0.6.121" />
      <ConnectionFields conn={conn} setConn={setConn} ips={[wiredIp.trim(), wirelessIp.trim()]} saved={printer} />
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
