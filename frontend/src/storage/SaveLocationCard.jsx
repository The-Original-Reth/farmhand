import { useEffect, useState } from "react";
import { ChevronDown, FolderDown, FolderOpen, HardDrive, RefreshCw, Save } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { errorText, getSaveLocation, reconnectShare, setSaveLocation } from "../api.js";
import { monoText, panelBox, primaryButton, uiText } from "../styles.js";
import { plural } from "../lib/format.js";
import { FieldSelect, TextField } from "../components/common/fields.jsx";
import { Badge } from "../components/common/ui.jsx";
import { FolderPicker } from "./FolderPicker.jsx";

// What each folder inside the save location holds, in the order shown
const FOLDERS = [
  ["stl", "STL", "STL / OBJ / STEP files"],
  ["threemf", "3MF", "3MF and G-code files"],
  ["project", "Projects", "Project files"],
  ["farmCost", "farm-cost", "Farm cost records"],
  ["config", "farmhand-configs", "Settings (Save all)"],
];

// A folder picked on a connected share, as its NAS address and that share: /data/nas/truenas/Farmhand on //nas/share
// is //nas/share/Farmhand. null when it isn't on one.
function pickedAt(path, shares) {
  const share = shares
    .filter((s) => s.mountPoint && (path === s.mountPoint || path.startsWith(`${s.mountPoint}/`)))
    .sort((a, b) => b.mountPoint.length - a.mountPoint.length)[0];
  if (!share) return null;
  const rest = path.slice(share.mountPoint.length).replace(/^\/+/, "");
  const base = share.protocol === "nfs" ? `${share.server}:/${share.share.replace(/^\/+/, "")}` : `//${share.server}/${share.share}`;
  return { address: rest ? `${base}/${rest}` : base, share };
}

const looksNfs = (address) => /^nfs:\/\//i.test(address.trim()) || /^[^/\\]+:\//.test(address.trim()); // nas:/volume1/...

// The save location: the one place on the NAS everything goes, typed as its address with its login. Farmhand connects
// to it and uses (or makes) a folder inside it for each kind of file. Its Advanced fold has the network share's own
// settings (how it's connected, Reconnect, the workgroup and the SMB / NFS version). Then Save all / Load all settings.
// shares: the connected shares (the first one fills the address in until a location is saved). copy: useSettingsCopy.
// onSaved(result): the folders changed (the page reloads; result.configChoice asks about settings already there).
export function SaveLocationCard({ shares, copy, onSaved }) {
  const [location, setLocation] = useState(null); // as the server has it: { address, share, capability, folders }
  const [address, setAddress] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [domain, setDomain] = useState("");
  const [version, setVersion] = useState("auto");
  const [advanced, setAdvanced] = useState(false);
  const [picking, setPicking] = useState(false); // the folder browser, to pick the save location
  const [busy, setBusy] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  // what's shown in the boxes: the save location's own share, else (until one is saved) the share already connected
  const fill = (l) => {
    const share = l.share || shares[0];
    setAddress(l.address || (share ? `//${share.server}/${share.share}` : ""));
    setUsername(share?.username || "");
    setDomain(share?.domain || "");
    setVersion(share?.version || "auto");
  };
  const load = () =>
    getSaveLocation()
      .then((l) => {
        setLocation(l);
        return l;
      })
      .catch((e) => setError(errorText(e)));
  useEffect(() => {
    load().then((l) => l && fill(l));
  }, []);

  const nfs = looksNfs(address);
  const versions = nfs ? ["4", "3"] : ["auto", "3.1.1", "3.0", "2.1"];
  const versionValue = versions.includes(version) ? version : versions[0]; // switching SMB / NFS while typing resets it

  // `picked`: { address, share } chosen with Browse… (used at once, with that share's own login, domain and version left
  // as they are); else the address and login typed
  const use = async (picked) => {
    const at = (picked ? picked.address : address).trim();
    setError(null);
    setDone(false);
    if (!at) return setError("Type the NAS address, like //192.168.1.50/share/Farmhand.");
    setBusy(true);
    try {
      const r = await setSaveLocation(
        picked
          ? { address: at, username: picked.share.username || null }
          : {
              address: at,
              username: nfs ? null : username.trim(),
              password,
              domain: nfs ? "" : domain.trim(),
              version: versionValue === "auto" ? "" : versionValue,
            },
      );
      setLocation(r);
      if (picked) fill(r); // the boxes show the picked share's own login
      setPassword("");
      setDone(true);
      await onSaved(r);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const reconnect = async () => {
    setError(null);
    setReconnecting(true);
    try {
      await reconnectShare(location.share.id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      await load();
      setReconnecting(false);
    }
  };

  const btn = { ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.borderStrong}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" };
  const saved = location?.address;
  const share = location?.share;
  const capability = location?.capability;
  const cannotMount = capability && !capability.ok;
  return (
    <div data-testid="save-location-card" style={panelBox({ padding: 16 })}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div style={uiText(15, c.heading, { fontWeight: 700 })}>Save location</div>
        {share && (share.mounted ? <Badge tone="green">connected</Badge> : <Badge tone="amber">not connected</Badge>)}
      </div>
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
        The one place on your NAS where Farmhand keeps everything. Type its address and login: Farmhand connects to it, and
        uses a folder inside it for each kind of file, making the ones that aren't there yet.
      </div>
      {cannotMount && (
        <div data-testid="capability-warning" style={uiText(12, c.amber, { lineHeight: 1.6, border: `1px solid ${c.amber}`, background: c.amberDim, borderRadius: 4, padding: "10px 12px", marginBottom: 12 })}>
          {capability.message}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <TextField label="NAS address" value={address} onChange={setAddress} placeholder="e.g. //192.168.1.50/share/Farmhand" />
        </div>
        <button
          data-testid="save-location-browse"
          onClick={() => setPicking(true)}
          title="Pick the folder on a connected network share"
          style={{ ...btn, display: "flex", alignItems: "center", gap: 6, marginBottom: 14, padding: "8px 12px", whiteSpace: "nowrap" }}
        >
          <FolderOpen size={13} />
          Browse…
        </button>
      </div>
      {!nfs && (
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
              placeholder={share?.hasPassword ? "Leave blank to keep the saved one" : ""}
            />
          </div>
        </div>
      )}

      <button
        data-testid="save-location-advanced"
        aria-expanded={advanced}
        onClick={() => setAdvanced(!advanced)}
        style={{ display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", padding: 0, marginBottom: advanced ? 10 : 14, cursor: "pointer", ...ui, fontSize: fs(12), color: c.textMuted }}
      >
        <ChevronDown size={13} style={{ transform: advanced ? "none" : "rotate(-90deg)", transition: "transform 0.12s ease" }} />
        <span style={{ fontWeight: 700 }}>Advanced</span>
        <span style={{ color: c.textFaint }}>the network share</span>
      </button>
      {advanced && (
        <div data-testid="save-location-share" style={{ borderLeft: `2px solid ${c.border}`, paddingLeft: 12, marginLeft: 6, marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
            {share ? (
              <>
                <span style={uiText(12, share.mounted ? c.green : c.amber, { lineHeight: 1.5, flex: "1 1 260px" })}>
                  {share.mounted ? `Connected to ${share.address}` : `Not connected${share.error ? `: ${share.error}` : "."}`}
                  <span style={{ color: c.textFaint }}> · mounted at </span>
                  <span style={monoText(12, c.textMuted)}>{share.mountPoint}</span>
                </span>
                <button data-testid="save-location-reconnect" onClick={reconnect} disabled={reconnecting} style={{ ...btn, display: "flex", alignItems: "center", gap: 6 }}>
                  <RefreshCw size={12} />
                  {reconnecting ? "Reconnecting…" : "Reconnect"}
                </button>
              </>
            ) : (
              <span style={uiText(12, c.textFaint)}>Not connected yet: the share is set up when the location is saved.</span>
            )}
          </div>
          {!nfs && <TextField label="Domain / workgroup (optional)" value={domain} onChange={setDomain} />}
          <FieldSelect
            label={`${nfs ? "NFS" : "SMB"} version`}
            value={versionValue}
            onChange={setVersion}
            options={versions.map((v) => ({ value: v, label: v === "auto" ? "Automatic (recommended)" : v }))}
          />
          <div style={uiText(12, c.textFaint, { lineHeight: 1.6 })}>
            Changes here are tried on a test connection first, so a typo can't break the one in use. Farmhand mounts the share
            itself: its container needs the SYS_ADMIN and DAC_READ_SEARCH permissions (see the README).
          </div>
        </div>
      )}

      {error && <div data-testid="save-location-error" style={uiText(12, c.amber, { lineHeight: 1.5, marginBottom: 10 })}>{error}</div>}
      {done && !error && (
        <div data-testid="save-location-done" style={uiText(12, c.green, { marginBottom: 10 })}>
          Connected. Everything now goes inside {location.address}.
        </div>
      )}
      <button data-testid="save-location-use" onClick={() => use()} disabled={busy || cannotMount} style={{ ...primaryButton(busy || cannotMount), marginBottom: 14 }}>
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
          Saved all settings to {copy.saved.path}.
          {copy.saved.records &&
            ` Wrote ${plural(copy.saved.records.projects, "project record")} into the project folders, and ${plural(copy.saved.records.library, "model or 3MF record", "model and 3MF records")} beside their files.`}
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
        <b style={{ color: c.textMuted }}>Save all</b> writes every setting to the farmhand-configs folder: the look, the storage
        and share setup, the farm cost folder, the Power page's prices, how the Printers, Monitor and Farm cost pages are
        arranged, and your printers and models. It also writes each project's record (its 3MFs, STLs and other files, and its
        parts list) into the project's folder, and each model's and 3MF's beside its files, so they can be brought back from
        there. <b style={{ color: c.textMuted }}>Load all settings</b> brings it back. A share's
        password is never saved; the printers' API keys and PrusaLink passwords are, so keep the folder private.
      </div>

      {picking && (
        <FolderPicker
          title="Choose the save location"
          startPath={location?.folders?.config ? location.folders.config.replace(/\/[^/]+$/, "") : shares.find((s) => s.mounted)?.mountPoint || null}
          shares={shares}
          onSelect={async (path) => {
            const picked = pickedAt(path, shares);
            if (!picked) {
              throw new Error(
                "Pick a folder on a connected network share. To use another NAS, type its address and login here first, then Browse inside it.",
              );
            }
            setAddress(picked.address);
            await use(picked);
          }}
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}
