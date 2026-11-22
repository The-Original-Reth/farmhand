import { useEffect, useState } from "react";
import { ChevronDown, FolderOpen } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { errorText, getSaveLocation, reconnectShare, setSaveLocation } from "../api.js";
import { panelBox, primaryButton, uiText } from "../styles.js";
import { TextField } from "../components/common/fields.jsx";
import { Badge } from "../components/common/ui.jsx";
import { FolderPicker } from "./FolderPicker.jsx";
import { SaveAllSettings, SaveLocationFolders, ShareSettings } from "./SaveLocationParts.jsx";

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
// to it and uses (or makes) a folder inside it for each kind of file, each listed with its own Change… (onChangeFolder(key):
// that folder alone moved somewhere else; `refresh` going up reads the list again). Its Advanced fold has the network share's own
// settings (how it's connected, Reconnect, the workgroup and the SMB / NFS version). Then Save all / Load all settings.
// shares: the connected shares (the first one fills the address in until a location is saved). copy: useSettingsCopy.
// onSaved(result): the folders changed (the page reloads; result.configChoice asks about settings already there).
export function SaveLocationCard({ shares, copy, onSaved, onChangeFolder, refresh = 0 }) {
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
  useEffect(() => {
    if (refresh) load(); // a folder changed with its Change…: the list as it is now
  }, [refresh]);

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
        <ShareSettings
          share={share} reconnect={reconnect} reconnecting={reconnecting} nfs={nfs} domain={domain} setDomain={setDomain}
          versions={versions} versionValue={versionValue} setVersion={setVersion} btn={btn}
        />
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

      {location && <SaveLocationFolders location={location} shares={shares} onChangeFolder={onChangeFolder} btn={btn} />}

      <SaveAllSettings copy={copy} btn={btn} />

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
