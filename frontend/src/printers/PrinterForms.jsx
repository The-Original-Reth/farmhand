import { useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { fieldBox, toolButton, uiText } from "../styles.js";
import { createPrinter, errorText, getPrusaLinkPassword, getStatusReporters, updatePrinter } from "../api.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";

import { ModalActions } from "../components/common/dialogs.jsx";
import { FieldSelect, TextField } from "../components/common/fields.jsx";
import { CameraNetworkSwitch, savedNetwork } from "./CameraNetworkSwitch.jsx";

// How Farmhand reaches a printer, as both printer forms ask it. conn: { type: "moonraker" | "prusalink" | "plugin:<id>",
// moonrakerUrl,
// apiKey, removeKey, prusalinkUrl, prusalinkUsername, prusalinkPassword, cameraAddress }. saved: the printer as it is (Edit), for
// saying a key or password is already saved; null when adding. ips: the wired and wireless IPs typed above (either may be
// blank), for the default addresses: Moonraker and PrusaLink are each tried at both, wired first.
const CONNECTIONS = [
  { value: "moonraker", label: "Mainsail or Fluidd (Moonraker / Klipper: Voron...)" },
  { value: "prusalink", label: "PrusaLink (Prusa Core One, MK4, XL...)" },
];
// "plugin:<id>": a Prusa printer connected through a plugin that reports printers and starts their prints (the Prusa
// Connect plugin), one choice per such plugin. Farmhand then asks the printer's PrusaLink for one thing only: reading
// the start of each printed file for its filament price (read only), with the PrusaLink login if one is given.
const viaPlugin = (type) => (type?.startsWith("plugin:") ? type.slice(7) : null);
const newConnection = (printer = null) => ({
  type: printer?.statusFrom ? `plugin:${printer.statusFrom}` : printer?.connectionType || "moonraker",
  moonrakerUrl: printer?.moonrakerUrlOverride || "",
  apiKey: "", // blank = keep whatever is saved
  removeKey: false,
  prusalinkUrl: printer?.prusalinkUrlOverride || "",
  prusalinkUsername: printer?.prusalinkUsername || "maker",
  prusalinkPassword: "", // blank = keep whatever is saved
  cameraAddress: printer?.cameraAddress || "", // a Buddy3D camera's IP, or a Klipper printer's camera's rtsp:// address
});

// The Connection choices: Mainsail or Fluidd (Klipper) and PrusaLink, and each plugin printers can be connected through (Prusa Connect)
function useConnections(current) {
  const [reporters, setReporters] = useState([]);
  useEffect(() => {
    getStatusReporters().then(setReporters).catch(() => setReporters([]));
  }, []);
  const chosen = viaPlugin(current);
  return [
    ...CONNECTIONS,
    ...reporters.map((r) => ({ value: `plugin:${r.id}`, label: `${r.name} (Prusa printers, through its plugin)` })),
    ...(chosen && !reporters.some((r) => r.id === chosen) ? [{ value: current, label: `${chosen} (its plugin isn't available)` }] : []),
  ];
}
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
  viaPlugin(conn.type)
    ? {
      connectionType: "prusalink", statusFrom: viaPlugin(conn.type), cameraAddress: conn.cameraAddress.trim(),
      prusalinkPassword: conn.prusalinkPassword || undefined, // only for reading printed files' filament price
    }
    : conn.type === "prusalink"
    ? {
        connectionType: "prusalink",
        prusalinkUrl: conn.prusalinkUrl.trim(),
        prusalinkUsername: conn.prusalinkUsername.trim() || "maker",
        prusalinkPassword: conn.prusalinkPassword || undefined,
        cameraAddress: conn.cameraAddress.trim(),
      }
    : {
        connectionType: "moonraker", moonrakerUrl: conn.moonrakerUrl.trim(),
        moonrakerApiKey: conn.removeKey ? "" : conn.apiKey.trim() || undefined, cameraAddress: conn.cameraAddress.trim(),
      };

function ConnectionFields({ conn, setConn, ips, saved = null }) {
  const set = (key) => (value) => setConn((c) => ({ ...c, [key]: value }));
  const [ip, otherIp] = ips.filter(Boolean);
  const both = otherIp && otherIp !== ip;
  const connections = useConnections(conn.type);
  const plugin = viaPlugin(conn.type);
  const camera = (
    <TextField
      label="Buddy3D camera IP (optional)"
      value={conn.cameraAddress}
      onChange={set("cameraAddress")}
      placeholder="e.g. 192.168.10.131. Turn on local streaming for it in the Prusa app"
    />
  );
  return (
    <>
      <FieldSelect label="Connection" value={conn.type} onChange={set("type")} options={connections} />
      {plugin ? (
        <>
          <div data-testid="connection-through-plugin" style={uiText(12, c.textFaint, { marginTop: -6, marginBottom: 14, lineHeight: 1.5 })}>
            Farmhand gets this printer's status from {connections.find((o) => o.value === conn.type)?.label.split(" (")[0] || "the plugin"},
            and sends its prints there too. Choose which printer it is on the plugin's page.
          </div>
          <PrusaLinkPassword value={conn.prusalinkPassword} onChange={set("prusalinkPassword")} saved={saved} />
          <div style={uiText(11, c.textFaint, { marginTop: -8, marginBottom: 14, lineHeight: 1.5 })}>
            Optional: with it, Farmhand reads the start of each printed file on the printer (only reads) for its filament
            price, as a Klipper printer&apos;s are costed. Nothing else goes to PrusaLink.
          </div>
          {camera}
        </>
      ) : conn.type === "prusalink" ? (
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
          {camera}
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
          <TextField
            label="Camera RTSP address (optional)"
            value={conn.cameraAddress}
            onChange={set("cameraAddress")}
            placeholder="e.g. rtsp://192.168.10.134:8554/stream. Leave blank to show Mainsail's camera"
          />
          <div style={uiText(11, c.textFaint, { marginTop: -8, marginBottom: 14, lineHeight: 1.5 })}>
            With it, Farmhand plays this camera itself, in place of Mainsail&apos;s first camera: the printer sends its video
            once, to Farmhand, however many pages show it. For a camera that takes few viewers or a busy Wi-Fi link (a
            Snapmaker U1&apos;s).
          </div>
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
  const [cameraNetwork, setCameraNetwork] = useState(null); // the Camera switch (null: not chosen)
  const [conn, setConn] = useState(() => newConnection());
  const { busy: submitting, error: errorMsg, setError: setErrorMsg, run } = useAction();

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!name.trim()) return setErrorMsg("A printer needs a name.");
    await run(async () => {
      putPrinter(await createPrinter({
        name: name.trim(), kind: kind.trim(), wiredIp: wiredIp.trim(), wirelessIp: wirelessIp.trim(), ...connectionFields(conn),
        cameraNetwork: savedNetwork(cameraNetwork, wiredIp.trim(), wirelessIp.trim()) || undefined,
      }));
      onClose();
    });
  };

  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="Must match the printer profile name inside your 3MF files exactly" />
      <TextField label="Type (optional)" value={kind} onChange={setKind} placeholder="e.g. Prusa Core One" />
      <TextField label="Wired IP (optional)" value={wiredIp} onChange={setWiredIp} placeholder="e.g. 10.0.6.21" />
      <TextField label="Wireless IP (optional)" value={wirelessIp} onChange={setWirelessIp} placeholder="e.g. 10.0.6.121" />
      <CameraNetworkSwitch value={cameraNetwork} onChange={setCameraNetwork} wiredIp={wiredIp.trim()} wirelessIp={wirelessIp.trim()} />
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
  const [cameraNetwork, setCameraNetwork] = useState(printer.cameraNetworkChoice || null); // the Camera switch (null: not chosen)
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
        cameraNetwork: savedNetwork(cameraNetwork, wiredIp.trim(), wirelessIp.trim()), // "" when not chosen, or its IP has gone
        // back to its own PrusaLink from a plugin
        ...(conn.type === "prusalink" && printer.statusFrom ? { statusFrom: "" } : {}),
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
      <CameraNetworkSwitch value={cameraNetwork} onChange={setCameraNetwork} wiredIp={wiredIp.trim()} wirelessIp={wirelessIp.trim()} />
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
