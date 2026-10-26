import { useEffect, useState } from "react";
import { HardDrive } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { cancelButton, monoText, primaryButton, uiText } from "../styles.js";
import {
  deleteShare,
  getConfig,
  getShares,
  getStorageSettings,
  inspectConfigFolder,
  migrateStorage,
  reconnectShare,
  restoreConfig,
  saveConfigNow,
  saveStorageSettings,
  setConfigLocation,
} from "../api.js";

import { ConfirmDialog, DeleteWarning, Modal } from "../components/common/dialogs.jsx";
import { Badge, SectionLabel } from "../components/common/ui.jsx";
import { formatBytes } from "../lib/format.js";
import { ConfigLocationCard, RestoreResult } from "./ConfigLocationCard.jsx";
import { FolderPicker } from "./FolderPicker.jsx";
import { ShareForm, SharesCard } from "./Shares.jsx";

function LocationCard({ title, blurb, location, onChange, onReset }) {
  const s = location.status;
  const problem = !s.exists
    ? "Folder not found"
    : !s.writable
      ? "Not writable"
      : !s.markerOk
        ? "Marker missing — the share may be unmounted"
        : null;
  return (
    <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div style={uiText(15, c.heading)}>{title}</div>
        <div style={{ display: "flex", gap: 6 }}>
          <Badge tone={location.isDefault ? "muted" : "teal"}>{location.isDefault ? "default location" : "chosen location"}</Badge>
          {s.ready ? <Badge tone="green">ready</Badge> : <Badge tone="amber">{problem}</Badge>}
        </div>
      </div>
      <div style={uiText(12, c.textFaint, { marginBottom: 12 })}>{blurb}</div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", border: `1px solid ${c.border}`, borderRadius: 4, background: c.panelAlt, marginBottom: 10 }}>
        <HardDrive size={15} color={c.textFaint} />
        <span style={monoText(12, c.heading, { wordBreak: "break-all" })}>{location.path}</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        {s.separateVolume ? <Badge tone="teal">separate volume (network or external)</Badge> : <Badge>same disk as the app</Badge>}
        <span style={uiText(12, c.textFaint)}>
          {formatBytes(s.freeBytes)} free of {formatBytes(s.totalBytes)}
        </span>
      </div>
      {!location.isDefault && !s.separateVolume && (
        <div style={uiText(12, c.amber, { marginBottom: 12, lineHeight: 1.5 })}>
          This folder is on the same disk as Farmhand's own data. If you meant a network share, check that it's mounted.
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={onChange}
          style={{ ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.borderStrong}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" }}
        >
          Change…
        </button>
        {!location.isDefault && (
          <button
            onClick={onReset}
            style={{ ...ui, fontSize: fs(13), background: "none", color: c.textFaint, border: `1px solid ${c.border}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" }}
          >
            Use default
          </button>
        )}
      </div>
    </div>
  );
}

export function StorageSection({ onSettingsRestored }) {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [picker, setPicker] = useState(null); // null | "stl" | "threemf"
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveResult, setMoveResult] = useState(null);
  const [sharesInfo, setSharesInfo] = useState(null);
  const [shareForm, setShareForm] = useState(null); // null | { existing?: share }
  const [removing, setRemoving] = useState(null); // null | share
  const [shareBusy, setShareBusy] = useState(null);
  const [shareError, setShareError] = useState(null);
  const [configInfo, setConfigInfo] = useState(null); // where the settings copy goes
  const [configPicker, setConfigPicker] = useState(false);
  const [configFound, setConfigFound] = useState(null); // the folder just chosen already holds a settings file
  const [configRestoreOpen, setConfigRestoreOpen] = useState(false);
  const [configResult, setConfigResult] = useState(null);
  const [configBusy, setConfigBusy] = useState(false);
  const [configError, setConfigError] = useState(null);

  useEffect(() => {
    Promise.all([getStorageSettings(), getShares(), getConfig().catch(() => null)])
      .then(([storageInfo, sharesData, config]) => {
        setInfo(storageInfo);
        setSharesInfo(sharesData);
        setConfigInfo(config ? config.location : null);
      })
      .catch((e) => setError(e.message || String(e)));
  }, []);

  if (error) {
    return <div style={uiText(13, c.amber)}>Couldn't load storage settings: {error}</div>;
  }
  if (!info || !sharesInfo) {
    return <div style={uiText(13, c.textFaint)}>Loading storage settings…</div>;
  }

  // Shares and the storage locations affect each other (a share's files, what's "ready"), so refresh both
  const reloadAll = async () => {
    const [storageInfo, sharesData] = await Promise.all([getStorageSettings(), getShares()]);
    setInfo(storageInfo);
    setSharesInfo(sharesData);
  };
  const refreshConfigInfo = async () => {
    try {
      setConfigInfo((await getConfig()).location);
    } catch {
      /* leave what's shown */
    }
  };
  const chooseConfigFolder = async (path) => {
    setConfigError(null);
    const found = await inspectConfigFolder(path); // refuses (with the reason) a folder that can't be used
    if (found.fileExists) {
      setConfigFound(found); // never overwrite settings that are already there without being told to
      return;
    }
    setConfigInfo((await setConfigLocation({ path })).location);
  };
  const resolveFound = async (choice) => {
    setConfigBusy(true);
    setConfigError(null);
    try {
      const r = await setConfigLocation({ path: configFound.path, ifExists: choice });
      setConfigInfo(r.location);
      if (r.restored) {
        setConfigResult(r.restored);
        onSettingsRestored();
        await reloadAll();
      }
      setConfigFound(null);
    } catch (e) {
      setConfigError(e.message || String(e));
    } finally {
      setConfigBusy(false);
    }
  };
  const clearConfigFolder = async () => {
    setConfigError(null);
    setConfigInfo((await setConfigLocation({ path: null })).location);
  };
  const saveConfigCopyNow = async () => {
    setConfigError(null);
    try {
      const r = await saveConfigNow();
      if (!r.ok) setConfigError(r.error);
    } catch (e) {
      setConfigError(e.message || String(e));
    }
    await refreshConfigInfo();
  };
  const reconnect = async (sh) => {
    setShareError(null);
    setShareBusy(sh.id);
    try {
      await reconnectShare(sh.id);
    } catch (e) {
      setShareError(`${sh.name}: ${e.message || e}`);
    } finally {
      setShareBusy(null);
      await reloadAll().catch(() => {});
    }
  };

  const body = (kind, path) => (kind === "stl" ? { stlPath: path } : { threemfPath: path });
  const resetLocation = async (kind) => {
    setActionError(null);
    try {
      setInfo(await saveStorageSettings(body(kind, null)));
    } catch (e) {
      setActionError(e.message || String(e));
    }
  };
  const outsideStl = info.outside.stl;
  const outsideThreemf = info.outside.threemf;
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 820 }}>
      <SectionLabel>Where files are stored</SectionLabel>

      <SharesCard
        data={sharesInfo}
        onAdd={() => setShareForm({})}
        onEdit={(sh) => setShareForm({ existing: sh })}
        onReconnect={reconnect}
        onRemove={async (sh) => {
          setShareError(null);
          try {
            const fresh = await getShares();
            setSharesInfo(fresh);
            setRemoving(fresh.shares.find((x) => x.id === sh.id) || sh);
          } catch {
            setRemoving(sh);
          }
        }}
        busyId={shareBusy}
        actionError={shareError}
      />

      <LocationCard
        title="STL / OBJ / STEP files"
        blurb="The source model files in the Models library."
        location={info.stl}
        onChange={() => setPicker("stl")}
        onReset={() => resetLocation("stl")}
      />
      <LocationCard
        title="3MF and gcode files"
        blurb="The sliced bundles and their gcode."
        location={info.threemf}
        onChange={() => setPicker("threemf")}
        onReset={() => resetLocation("threemf")}
      />
      {actionError && <div style={uiText(12, c.amber)}>{actionError}</div>}

      {outsideStl + outsideThreemf > 0 && (
        <div style={{ border: `1px solid ${c.borderStrong}`, borderRadius: 4, background: c.panelAlt, padding: 16 }}>
          <div style={uiText(13, c.textPrimary, { marginBottom: 6 })}>
            {[
              outsideStl > 0 && plural(outsideStl, "STL version", "STL versions"),
              outsideThreemf > 0 && plural(outsideThreemf, "3MF version", "3MF versions"),
            ]
              .filter(Boolean)
              .join(" and ")}{" "}
            still {outsideStl + outsideThreemf === 1 ? "has" : "have"} files in a previous location.
          </div>
          <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
            They keep working where they are — only new uploads use the locations above. Moving copies each file into its
            chosen location, checks the copy, and only then removes the original.
          </div>
          <button
            onClick={() => setMoveOpen(true)}
            style={{ ...ui, fontSize: fs(13), background: c.amber, color: c.onAccent, border: "none", borderRadius: 4, padding: "7px 14px", fontWeight: 600, cursor: "pointer" }}
          >
            Move them now…
          </button>
        </div>
      )}

      {moveResult && (
        <div data-testid="move-result" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 14, ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6 }}>
          Moved {plural(moveResult.movedStl, "STL version", "STL versions")} and{" "}
          {plural(moveResult.movedThreemf, "3MF version", "3MF versions")}.
          {moveResult.missing.length > 0 && (
            <div style={{ color: c.amber, marginTop: 6 }}>
              Not found on disk (skipped): <span style={mono}>{moveResult.missing.join(", ")}</span>
            </div>
          )}
          {moveResult.failed.map((f) => (
            <div key={f.name} style={{ color: c.amber, marginTop: 6 }}>
              Couldn't move <span style={mono}>{f.name}</span>: {f.error}
            </div>
          ))}
        </div>
      )}

      <div style={uiText(12, c.textFaint, { lineHeight: 1.7 })}>
        <div>
          <b style={{ color: c.textMuted }}>Network shares.</b> Farmhand mounts them itself, so there's nothing to set up on
          the computer running it. To do that its container is given the SYS_ADMIN and DAC_READ_SEARCH permissions (see the README).
        </div>
        <div style={{ marginTop: 6 }}>
          <b style={{ color: c.textMuted }}>Safety check.</b> Chosen folders get a small <span style={mono}>.farmhand-storage</span>{" "}
          marker. If a share drops and leaves an empty folder behind, the marker is missing and uploads are refused rather
          than silently filling the local disk.
        </div>
        <div style={{ marginTop: 6 }}>
          <b style={{ color: c.textMuted }}>Thumbnails</b> always stay on the app's local disk, so browsing keeps working
          if a share is offline.
        </div>
      </div>

      <SectionLabel>Settings</SectionLabel>
      <ConfigLocationCard
        info={configInfo}
        error={configError}
        onChoose={() => setConfigPicker(true)}
        onSaveNow={saveConfigCopyNow}
        onRestore={() => setConfigRestoreOpen(true)}
        onClear={clearConfigFolder}
      />
      {configResult && <RestoreResult result={configResult} />}

      {configPicker && (
        <FolderPicker
          title="Choose the folder for Farmhand's settings"
          startPath={configInfo?.isSet ? configInfo.path : null}
          shares={sharesInfo.shares}
          onSelect={chooseConfigFolder}
          onClose={() => setConfigPicker(false)}
        />
      )}

      {configFound && (
        <Modal title="Settings already in that folder" onClose={() => (configBusy ? undefined : setConfigFound(null))} width={580}>
          <div data-testid="config-found" style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 14 })}>
            {configFound.fileValid ? (
              <>
                That folder already has a Farmhand settings file
                {configFound.summary?.savedAt ? <> (saved {new Date(configFound.summary.savedAt).toLocaleString()})</> : null}: colour scheme{" "}
                <b style={{ color: c.heading }}>{configFound.summary?.scheme}</b>
                {configFound.summary?.shares ? `, ${configFound.summary.shares} network share${configFound.summary.shares === 1 ? "" : "s"}` : ""}
                {configFound.summary?.printers ? `, ${configFound.summary.printers} printer${configFound.summary.printers === 1 ? "" : "s"}` : ""}
                {configFound.summary?.models ? `, notes for ${configFound.summary.models} model${configFound.summary.models === 1 ? "" : "s"}` : ""}. What
                should Farmhand do with it?
              </>
            ) : (
              <>
                That folder has a settings file Farmhand can't use: <span style={{ color: c.amber }}>{configFound.error}</span> It can be
                replaced with the current settings, or you can pick another folder.
              </>
            )}
          </div>
          {configError && <div style={uiText(12, c.amber, { marginBottom: 10 })}>{configError}</div>}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
            <button
              onClick={() => setConfigFound(null)}
              disabled={configBusy}
              style={cancelButton()}
            >
              Cancel
            </button>
            <button
              data-testid="config-found-overwrite"
              onClick={() => resolveFound("overwrite")}
              disabled={configBusy}
              style={{ ...ui, fontSize: fs(13), background: "none", color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 3, padding: "7px 14px", cursor: "pointer" }}
            >
              Replace with current settings
            </button>
            {configFound.fileValid && (
              <button
                data-testid="config-found-restore"
                onClick={() => resolveFound("restore")}
                disabled={configBusy}
                style={primaryButton()}
              >
                {configBusy ? "Working…" : "Use those settings"}
              </button>
            )}
          </div>
        </Modal>
      )}

      {configRestoreOpen && (
        <ConfirmDialog
          title="Restore settings from the network folder"
          confirmLabel="Restore"
          tone="primary"
          onClose={() => setConfigRestoreOpen(false)}
          onConfirm={async () => {
            const result = await restoreConfig();
            setConfigResult(result);
            onSettingsRestored();
            await reloadAll();
          }}
        >
          <div>
            Load the settings saved in that folder? This replaces the current look and display preferences with the saved
            ones, puts back the STL and 3MF folders it lists, and adds any network shares that aren't already here. Passwords
            aren't saved, so those shares will need theirs typed in.
          </div>
        </ConfirmDialog>
      )}

      {picker && (
        <FolderPicker
          title={picker === "stl" ? "Choose the folder for STL files" : "Choose the folder for 3MF files"}
          startPath={(picker === "stl" ? info.stl : info.threemf).isDefault ? null : (picker === "stl" ? info.stl : info.threemf).path}
          shares={sharesInfo.shares}
          onSelect={async (path) => setInfo(await saveStorageSettings(body(picker, path)))}
          onClose={() => setPicker(null)}
        />
      )}

      {shareForm && (
        <Modal title={shareForm.existing ? `Edit ${shareForm.existing.name}` : "Add network share"} onClose={() => setShareForm(null)} width={500}>
          <ShareForm
            existing={shareForm.existing}
            capability={sharesInfo.capability}
            onClose={() => setShareForm(null)}
            onSaved={reloadAll}
          />
        </Modal>
      )}

      {removing && (
        <ConfirmDialog
          title="Remove network share"
          confirmLabel="Remove share"
          onClose={() => setRemoving(null)}
          onConfirm={async () => {
            await deleteShare(removing.id);
            await reloadAll();
          }}
        >
          <div>
            Disconnect <b style={{ color: c.heading }}>{removing.name}</b> and forget its login? Nothing on the NAS is
            deleted.
          </div>
          {removing.filesHere > 0 && (
            <DeleteWarning>
              {removing.filesHere === 1 ? "1 version has its files" : `${removing.filesHere} versions have their files`} stored
              on this share. Farmhand won't be able to open or download them until you add the share again.
            </DeleteWarning>
          )}
        </ConfirmDialog>
      )}

      {moveOpen && (
        <ConfirmDialog
          title="Move files to the chosen locations"
          confirmLabel="Move files"
          tone="primary"
          onClose={() => setMoveOpen(false)}
          onConfirm={async () => {
            setMoveResult(await migrateStorage());
            await reloadAll(); // locations AND shares: how many files live on each share just changed
          }}
        >
          <div>
            Move {[outsideStl > 0 && plural(outsideStl, "STL version", "STL versions"), outsideThreemf > 0 && plural(outsideThreemf, "3MF version", "3MF versions")].filter(Boolean).join(" and ")}{" "}
            into the locations above? Large files over a network can take a while — keep this page open until it finishes.
          </div>
        </ConfirmDialog>
      )}
    </div>
  );
}
