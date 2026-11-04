import { useState } from "react";
import { c, fs, ui } from "../theme.js";
import { errorText, getConfig, inspectConfigFolder, restoreConfig, saveConfigNow, setConfigLocation } from "../api.js";
import { cancelButton, primaryButton, uiText } from "../styles.js";
import { useAction } from "../hooks/useAction.js";

import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { ConfigLocationCard, RestoreResult } from "./ConfigLocationCard.jsx";
import { FolderPicker } from "./FolderPicker.jsx";

// Farmhand's settings copy on the NAS: where it goes, saving it now, restoring from it, and what to do when the folder
// chosen already holds one. initialInfo: its location as the Storage page loaded it. shares: the connected network
// shares, to pick a folder on. onSettingsRestored: the look and preferences came back. reloadAll: the Storage page
// reloads (a restore can bring back shares and folders).
export function SettingsCopy({ initialInfo, shares, onSettingsRestored, reloadAll }) {
  const [configInfo, setConfigInfo] = useState(initialInfo); // where the settings copy goes
  const [configPicker, setConfigPicker] = useState(false);
  const [configFound, setConfigFound] = useState(null); // the folder just chosen already holds a settings file
  const [configRestoreOpen, setConfigRestoreOpen] = useState(false);
  const [configResult, setConfigResult] = useState(null);
  const { busy: configBusy, error: configError, setError: setConfigError, run } = useAction();

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
  const resolveFound = (choice) =>
    run(async () => {
      const r = await setConfigLocation({ path: configFound.path, ifExists: choice });
      setConfigInfo(r.location);
      if (r.restored) {
        setConfigResult(r.restored);
        onSettingsRestored();
        await reloadAll();
      }
      setConfigFound(null);
    });
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
      setConfigError(errorText(e));
    }
    await refreshConfigInfo();
  };

  return (
    <>
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
          shares={shares}
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
    </>
  );
}
