import { useEffect, useState } from "react";
import { ArrowUp, Folder, FolderPlus, Server } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { cancelButton, monoText, primaryButton, uiText } from "../styles.js";
import { browseStorage, createFolder, errorText } from "../api.js";

import { Modal } from "../components/common/dialogs.jsx";
import { Badge } from "../components/common/ui.jsx";

export function FolderPicker({ title, startPath, shares = [], onSelect, onClose }) {
  const [listing, setListing] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const connected = shares.filter((sh) => sh.mounted);

  const load = async (path) => {
    setError(null);
    try {
      setListing(await browseStorage(path));
    } catch (e) {
      setError(errorText(e));
    }
  };

  useEffect(() => {
    // Open where the current choice is; if that's gone or out of bounds, start from the top
    browseStorage(startPath)
      .then(setListing)
      .catch(() => browseStorage(null).then(setListing).catch((e) => setError(errorText(e))));
  }, []);

  const makeFolder = async () => {
    setCreating(true);
    setError(null);
    try {
      setListing(await createFolder({ parent: listing.path, name: newName }));  // step into the new folder
      setNewOpen(false);
      setNewName("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setCreating(false);
    }
  };

  const choose = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSelect(listing.path);
      onClose();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };

  return (
    <Modal title={title} onClose={busy ? () => {} : onClose} width={580}>
      {!listing && !error && <div style={uiText(13, c.textFaint)}>Loading folders…</div>}
      {listing && connected.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          <span style={uiText(12, c.textFaint)}>Connected shares:</span>
          {connected.map((sh) => (
            <button
              key={sh.id}
              onClick={() => load(sh.mountPoint)}
              style={{ display: "flex", alignItems: "center", gap: 5, ...ui, fontSize: fs(12), background: c.tealDim, color: c.teal, border: `1px solid ${c.teal}`, borderRadius: 3, padding: "3px 9px", cursor: "pointer" }}
            >
              <Server size={11} />
              {sh.name}
            </button>
          ))}
        </div>
      )}
      {listing && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <button
              onClick={() => load(listing.parent)}
              disabled={!listing.parent}
              title="Up one folder"
              aria-label="Up one folder"
              style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 28, height: 28, flexShrink: 0, borderRadius: 3, border: `1px solid ${c.border}`, background: "transparent", color: listing.parent ? c.textMuted : c.textFaint, cursor: listing.parent ? "pointer" : "default" }}
            >
              <ArrowUp size={14} />
            </button>
            <div data-testid="picker-path" style={monoText(12, c.heading, { wordBreak: "break-all", flex: 1 })}>{listing.path}</div>
            <button
              onClick={() => setNewOpen((v) => !v)}
              style={{ display: "flex", alignItems: "center", gap: 5, flexShrink: 0, ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "4px 9px", cursor: "pointer" }}
            >
              <FolderPlus size={13} />
              New folder
            </button>
          </div>
          {newOpen && (
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && newName.trim() && !creating && makeFolder()}
                placeholder="Folder name"
                style={{ flex: 1, background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, padding: "7px 10px", fontSize: fs(13), ...ui }}
              />
              <button
                onClick={makeFolder}
                disabled={creating || !newName.trim()}
                style={{ ...ui, fontSize: fs(13), background: c.amberDim, color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 4, padding: "6px 12px", cursor: creating || !newName.trim() ? "default" : "pointer", opacity: creating || !newName.trim() ? 0.6 : 1 }}
              >
                {creating ? "Creating…" : "Create"}
              </button>
            </div>
          )}
          <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, maxHeight: 280, overflow: "auto", marginBottom: 10 }}>
            {listing.entries.length === 0 && (
              <div style={uiText(13, c.textFaint, { padding: "14px 16px" })}>No sub-folders here.</div>
            )}
            {listing.entries.map((e, i) => (
              <button
                key={e.path}
                onClick={() => load(e.path)}
                style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left", padding: "9px 14px", background: "transparent", border: "none", borderTop: i === 0 ? "none" : `1px solid ${c.border}`, color: c.textPrimary, cursor: "pointer", ...ui, fontSize: fs(13) }}
              >
                <Folder size={15} color={c.textFaint} />
                <span style={{ flex: 1 }}>{e.name}</span>
                {e.isMount && <Badge tone="teal">mounted share</Badge>}
              </button>
            ))}
          </div>
          <div style={uiText(11, c.textFaint, { lineHeight: 1.5, marginBottom: 14 })}>
            Only folders on a connected network share (or in Farmhand's own storage) can be chosen. Open a share
            above, then pick a folder on it — or make one with New folder.
          </div>
        </>
      )}
      {error && <div style={uiText(12, c.amber, { marginBottom: 12, lineHeight: 1.5 })}>{error}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button
          onClick={onClose}
          disabled={busy}
          style={cancelButton()}
        >
          Cancel
        </button>
        <button
          onClick={choose}
          disabled={busy || !listing}
          style={primaryButton(busy || !listing)}
        >
          {busy ? "Saving…" : "Use this folder"}
        </button>
      </div>
    </Modal>
  );
}
