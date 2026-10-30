import { useState } from "react";
import { Server } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { monoText, uiText } from "../styles.js";
import { createShare, updateShare } from "../api.js";
import { describeLocation, parseLocation } from "../location.js";
import { useAction } from "../hooks/useAction.js";

import { ModalActions } from "../components/common/dialogs.jsx";
import { FieldSelect, TextField } from "../components/common/fields.jsx";
import { Badge } from "../components/common/ui.jsx";

export function ShareForm({ existing, capability, onClose, onSaved }) {
  const editing = !!existing;
  const [name, setName] = useState(existing?.name || "");
  const [location, setLocation] = useState(existing?.address || ""); // ONE address: server, share and sub-folder together
  const [username, setUsername] = useState(existing?.username || "");
  const [password, setPassword] = useState("");
  const [domain, setDomain] = useState(existing?.domain || "");
  const [version, setVersion] = useState(existing?.version || "auto");
  const { busy: submitting, error: errorMsg, setError: setErrorMsg, run } = useAction();

  // How the address reads: decides SMB-only fields and the version list. Just a preview —
  // the server parses and validates the address itself.
  const parsed = parseLocation(location);
  const described = describeLocation(parsed);
  const protocol = editing ? existing.protocol : parsed.protocol || "smb";
  const smb = protocol === "smb";
  const versions = smb ? ["auto", "3.1.1", "3.0", "2.1"] : ["4", "3"];
  const versionValue = versions.includes(version) ? version : versions[0]; // switching SMB↔NFS while typing resets it

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!name.trim() && !editing) return setErrorMsg("Give the share a name.");
    if (!location.trim()) return setErrorMsg("Enter the NAS folder's address.");
    if (editing && parsed.protocol && parsed.protocol !== existing.protocol) {
      return setErrorMsg(`This is an ${existing.protocol.toUpperCase()} share — enter an ${existing.protocol.toUpperCase()} address, or add a new share instead.`);
    }
    await run(async () => {
      const versionOut = versionValue === "auto" ? "" : versionValue;
      const login = smb ? { username, domain } : {};
      if (editing) {
        await updateShare(existing.id, {
          location,
          ...login,
          version: versionOut,
          ...(smb && password ? { password } : {}), // blank keeps the saved password
        });
      } else {
        await createShare({ name, location, ...login, password: smb ? password || null : null, version: versionOut });
      }
      await onSaved();
      onClose();
    });
  };

  return (
    <>
      <TextField label="Name" value={name} onChange={setName} placeholder="e.g. Lab NAS" disabled={editing} />
      <TextField
        label="NAS folder address"
        value={location}
        onChange={setLocation}
        placeholder="e.g. //192.168.1.50/farmhand/Projects   or   192.168.1.50:/volume1/farmhand"
      />
      <div data-testid="location-preview" style={{ ...ui, fontSize: fs(12), lineHeight: 1.5, marginTop: -6, marginBottom: 14, color: described ? (described.ok ? c.teal : c.amber) : c.textFaint }}>
        {described
          ? described.text
          : "Paste the folder's full address — Farmhand works out the rest. SMB (//server/share) and NFS (server:/export) both work."}
      </div>
      {capability?.[`${protocol}_message`] && (
        <div data-testid="protocol-unavailable" style={uiText(12, c.amber, { lineHeight: 1.6, border: `1px solid ${c.amber}`, background: c.amberDim, borderRadius: 4, padding: "9px 12px", marginBottom: 14 })}>
          {capability[`${protocol}_message`]}
        </div>
      )}
      {smb && (
        <>
          <TextField label="Username (leave blank for guest access)" value={username} onChange={setUsername} placeholder="e.g. alice" />
          <TextField
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder={editing && existing.hasPassword ? "Leave blank to keep the saved password" : ""}
          />
          <TextField label="Domain / workgroup (optional)" value={domain} onChange={setDomain} placeholder="" />
        </>
      )}
      <FieldSelect
        label={`${smb ? "SMB" : "NFS"} version (advanced)`}
        placeholder="Choose…"
        value={versionValue}
        onChange={setVersion}
        options={
          smb
            ? [
                { value: "auto", label: "Automatic (recommended)" },
                { value: "3.1.1", label: "3.1.1" },
                { value: "3.0", label: "3.0" },
                { value: "2.1", label: "2.1" },
              ]
            : [
                { value: "4", label: "4 (recommended)" },
                { value: "3", label: "3" },
              ]
        }
      />
      <div style={uiText(11, c.textFaint, { marginBottom: 14, lineHeight: 1.5 })}>
        Farmhand connects right now and only saves the share if that works. The login is kept in Farmhand's database so
        it can reconnect after a restart; it's never shown again.
      </div>
      <ModalActions
        onClose={onClose}
        onSubmit={handleSubmit}
        actionLabel={editing ? "Save" : "Connect"}
        submittingLabel={editing ? "Saving…" : "Connecting…"}
        submitting={submitting}
        errorMsg={errorMsg}
      />
    </>
  );
}

export function SharesCard({ data, onAdd, onEdit, onReconnect, onRemove, busyId, actionError }) {
  const { shares, capability } = data;
  const btn = { ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "4px 10px", cursor: "pointer" };
  return (
    <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div style={uiText(15, c.heading)}>Network shares</div>
        <button
          onClick={onAdd}
          disabled={!capability.ok}
          style={{ display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(13), background: capability.ok ? c.amberDim : "none", color: capability.ok ? c.amber : c.textFaint, border: `1px solid ${capability.ok ? c.amber : c.border}`, borderRadius: 4, padding: "6px 12px", cursor: capability.ok ? "pointer" : "not-allowed" }}
        >
          <Server size={13} />
          Add network share…
        </button>
      </div>
      <div style={uiText(12, c.textFaint, { marginBottom: 12 })}>
        Connect your NAS here. Farmhand mounts it itself and reconnects after restarts — then choose folders on it below.
      </div>

      {!capability.ok && (
        <div data-testid="capability-warning" style={uiText(12, c.amber, { lineHeight: 1.6, border: `1px solid ${c.amber}`, background: c.amberDim, borderRadius: 4, padding: "10px 12px", marginBottom: 12 })}>
          {capability.message}
        </div>
      )}

      {capability.ok && (capability.smb_message || capability.nfs_message) && (
        <div data-testid="capability-partial" style={uiText(12, c.amber, { lineHeight: 1.6, border: `1px solid ${c.amber}`, background: c.amberDim, borderRadius: 4, padding: "10px 12px", marginBottom: 12 })}>
          {capability.smb_message && <div><b>SMB shares:</b> {capability.smb_message}</div>}
          {capability.nfs_message && <div><b>NFS shares:</b> {capability.nfs_message}</div>}
        </div>
      )}

      {shares.length === 0 && capability.ok && (
        <div style={uiText(13, c.textFaint)}>No network shares yet.</div>
      )}

      {shares.map((sh, i) => (
        <div key={sh.id} style={{ borderTop: i === 0 ? "none" : `1px solid ${c.border}`, padding: "10px 0" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ minWidth: 0 }}>
              <div style={uiText(14, c.heading, { display: "flex", alignItems: "center", gap: 8 })}>
                <Server size={14} color={c.textFaint} />
                {sh.name}
                {sh.mounted ? <Badge tone="green">connected</Badge> : <Badge tone="amber">not connected</Badge>}
              </div>
              <div style={monoText(11, c.textFaint, { marginTop: 3, wordBreak: "break-all" })}>
                {sh.address}
                {sh.username ? ` · ${sh.username}` : sh.protocol === "smb" ? " · guest" : ""}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
              {!sh.mounted && (
                <button onClick={() => onReconnect(sh)} disabled={busyId === sh.id} style={btn}>
                  {busyId === sh.id ? "Connecting…" : "Reconnect"}
                </button>
              )}
              <button onClick={() => onEdit(sh)} style={btn}>
                Edit
              </button>
              <button onClick={() => onRemove(sh)} style={btn}>
                Remove
              </button>
            </div>
          </div>
          {!sh.mounted && sh.error && (
            <div style={uiText(12, c.amber, { marginTop: 6, lineHeight: 1.5 })}>{sh.error}</div>
          )}
          {!sh.mounted && !sh.error && (
            <div style={uiText(12, c.textFaint, { marginTop: 6 })}>
              Farmhand will keep trying to connect to this in the background.
            </div>
          )}
        </div>
      ))}
      {actionError && <div style={uiText(12, c.amber, { marginTop: 8, lineHeight: 1.5 })}>{actionError}</div>}
    </div>
  );
}
