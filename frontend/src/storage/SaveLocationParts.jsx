import { FolderDown, HardDrive, RefreshCw, Save } from "lucide-react";
import { c, fs } from "../theme.js";
import { monoText, primaryButton, uiText } from "../styles.js";
import { plural } from "../lib/format.js";
import { FieldSelect, TextField } from "../components/common/fields.jsx";

// The parts of the save location's card (SaveLocationCard.jsx), which keeps their state. `btn` is the card's button style.

// What each folder inside the save location holds, in the order shown
const FOLDERS = [
  ["stl", "STL", "STL / OBJ / STEP files"],
  ["threemf", "3MF", "3MF and G-code files"],
  ["project", "Projects", "Project files"],
  ["farmCost", "farm-cost", "Farm cost records"],
  ["config", "farmhand-configs", "Settings (Save all)"],
  ["backups", "backup", "Printer config backups"],
];

// A folder as people reach it on the network, as Windows writes it: \\server\share\rest, from where Farmhand has it
// mounted (/data/nas/farm-nas/models on //192.168.10.5/farmhand is \\192.168.10.5\farmhand\models). The path as it
// is when it isn't on a connected share (Farmhand's own storage).
export function networkPath(path, shares) {
  if (!path) return path;
  const share = shares
    .filter((x) => x.mountPoint && (path === x.mountPoint || path.startsWith(`${x.mountPoint}/`)))
    .sort((x, y) => y.mountPoint.length - x.mountPoint.length)[0];
  if (!share) return path;
  const parts = [share.server, ...String(share.share).split("/"), ...path.slice(share.mountPoint.length).split("/")].filter(Boolean);
  return `\\\\${parts.join("\\")}`;
}

// Advanced: the network share's own settings (how it's connected, Reconnect, the workgroup and the SMB / NFS version)
export function ShareSettings({ share, reconnect, reconnecting, nfs, domain, setDomain, versions, versionValue, setVersion, btn }) {
  return (
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
  );
}

// Each folder inside the save location, with its own Change…
export function SaveLocationFolders({ location, shares, onChangeFolder, btn }) {
  return (
    <div data-testid="save-location-folders" style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panelAlt, marginBottom: 14 }}>
      {FOLDERS.map(([key, name, what], i) => (
        <div key={key} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 12px", borderTop: i ? `1px solid ${c.border}` : "none", flexWrap: "wrap" }}>
          <HardDrive size={13} color={c.textFaint} style={{ flexShrink: 0 }} />
          <span style={uiText(12, c.textMuted, { width: 170, flexShrink: 0 })}>{what}</span>
          <span
            title={location.folders[key] ? `Inside Farmhand's container: ${location.folders[key]}` : undefined}
            style={monoText(12, location.folders[key] ? c.heading : c.textFaint, { minWidth: 0, overflowWrap: "anywhere", flex: "1 1 200px" })}
          >
            {networkPath(location.folders[key], shares) || `not set yet (${name})`}
          </span>
          {onChangeFolder && (
            <button
              data-testid={`save-location-change-${key}`}
              onClick={() => onChangeFolder(key)}
              title={`Choose another folder for the ${what.toLowerCase()}`}
              style={{ ...btn, padding: "3px 10px", fontSize: fs(12), marginLeft: "auto", flexShrink: 0 }}
            >
              Change…
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

// Save all / Load all settings. copy: useSettingsCopy.
export function SaveAllSettings({ copy, btn }) {
  return (
    <>
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
    </>
  );
}
