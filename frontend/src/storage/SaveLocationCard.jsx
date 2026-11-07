import { useEffect, useState } from "react";
import { FolderDown, HardDrive, Save } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { errorText, getSaveLocation, setSaveLocation } from "../api.js";
import { monoText, panelBox, primaryButton, uiText } from "../styles.js";
import { TextField } from "../components/common/fields.jsx";

// What each folder inside the save location holds, in the order shown
const FOLDERS = [
  ["stl", "STL", "STL / OBJ / STEP files"],
  ["threemf", "3MF", "3MF and G-code files"],
  ["project", "Projects", "Project files"],
  ["farmCost", "Farm cost", "Farm cost records"],
  ["config", "Farmhand Configs", "Settings (Save all)"],
];

const looksNfs = (address) => /^nfs:\/\//i.test(address.trim()) || /^[^/\\]+:\//.test(address.trim()); // nas:/volume1/...

// The save location: the one place on the NAS everything goes, typed as its address with its login. Farmhand connects
// to it and uses (or makes) a folder inside it for each kind of file. Then Save all / Load all settings.
// shares: the connected shares (the first one fills the address in until a location is saved). copy: useSettingsCopy.
// onSaved(result): the folders changed (the page reloads; result.configChoice asks about settings already there).
export function SaveLocationCard({ shares, copy, onSaved }) {
  const [location, setLocation] = useState(null); // as the server has it: { address, folders }
  const [address, setAddress] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    getSaveLocation()
      .then((l) => {
        setLocation(l);
        const share = shares[0];
        // until a location is saved, suggest the share already connected
        setAddress(l.address || (share ? `//${share.server}/${share.share}` : ""));
        const same = shares.find((s) => (l.address || "").toLowerCase().includes(`${s.server}/${s.share}`.toLowerCase())) || share;
        setUsername(same?.username || "");
      })
      .catch((e) => setError(errorText(e)));
  }, []);

  const use = async () => {
    setError(null);
    setDone(false);
    if (!address.trim()) return setError("Type the NAS address, like //192.168.1.50/share/Farmhand.");
    setBusy(true);
    try {
      const r = await setSaveLocation({ address: address.trim(), username: looksNfs(address) ? null : username.trim(), password });
      setLocation(r);
      setPassword("");
      setDone(true);
      await onSaved(r);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const btn = { ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.borderStrong}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" };
  const saved = location?.address;
  return (
    <div data-testid="save-location-card" style={panelBox({ padding: 16 })}>
      <div style={uiText(15, c.heading, { fontWeight: 700, marginBottom: 4 })}>Save location</div>
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
        The one place on your NAS where Farmhand keeps everything. Type its address and login: Farmhand connects to it, and
        uses a folder inside it for each kind of file, making the ones that aren't there yet.
      </div>

      <TextField label="NAS address" value={address} onChange={setAddress} placeholder="e.g. //192.168.1.50/share/Farmhand" />
      {!looksNfs(address) && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 200px" }}>
            <TextField label="Username (blank for guest)" value={username} onChange={setUsername} />
          </div>
          <div style={{ flex: "1 1 200px" }}>
            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              placeholder={saved ? "Leave blank to keep the saved one" : ""}
            />
          </div>
        </div>
      )}
      {error && <div data-testid="save-location-error" style={uiText(12, c.amber, { lineHeight: 1.5, marginBottom: 10 })}>{error}</div>}
      {done && !error && (
        <div data-testid="save-location-done" style={uiText(12, c.green, { marginBottom: 10 })}>
          Connected. Everything now goes inside {location.address}.
        </div>
      )}
      <button data-testid="save-location-use" onClick={use} disabled={busy} style={{ ...primaryButton(busy), marginBottom: 14 }}>
        {busy ? "Connecting…" : saved ? "Save location" : "Use this location"}
      </button>

      {location && (
        <div data-testid="save-location-folders" style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panelAlt, marginBottom: 14 }}>
          {FOLDERS.map(([key, name, what], i) => (
            <div key={key} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 12px", borderTop: i ? `1px solid ${c.border}` : "none", flexWrap: "wrap" }}>
              <HardDrive size={13} color={c.textFaint} style={{ flexShrink: 0 }} />
              <span style={uiText(12, c.textMuted, { width: 170, flexShrink: 0 })}>{what}</span>
              <span style={monoText(12, location.folders[key] ? c.heading : c.textFaint, { minWidth: 0, overflowWrap: "anywhere" })}>
                {location.folders[key] || `not set yet (${name})`}
              </span>
            </div>
          ))}
        </div>
      )}

      {copy.error && <div style={uiText(12, c.amber, { lineHeight: 1.5, marginBottom: 10 })}>{copy.error}</div>}
      {copy.saved && !copy.error && (
        <div data-testid="config-saved" style={uiText(12, c.green, { lineHeight: 1.5, marginBottom: 10 })}>
          Saved all settings to {copy.saved}.
        </div>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button data-testid="config-save-all" onClick={copy.saveAll} disabled={copy.saving} style={{ ...primaryButton(copy.saving), display: "flex", alignItems: "center", gap: 6 }}>
          <Save size={13} />
          {copy.saving ? "Saving…" : "Save all"}
        </button>
        <button data-testid="config-load-all" onClick={copy.loadAll} style={{ ...btn, display: "flex", alignItems: "center", gap: 6 }}>
          <FolderDown size={13} />
          Load all settings…
        </button>
      </div>
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginTop: 10 })}>
        <b style={{ color: c.textMuted }}>Save all</b> writes every setting to the Farmhand Configs folder: the look, the storage
        and share setup, the farm cost folder, the Power page's prices, how the Printers, Monitor and Farm cost pages are
        arranged, and your printers and models. <b style={{ color: c.textMuted }}>Load all settings</b> brings it back. A share's
        password is never saved; the printers' API keys and PrusaLink passwords are, so keep the folder private.
      </div>
    </div>
  );
}
