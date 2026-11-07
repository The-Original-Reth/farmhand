import { useState } from "react";
import { c, fs, ui } from "../theme.js";
import { errorText, inspectConfigFolder, restoreConfig, saveAllSettings, setConfigLocation } from "../api.js";
import { cancelButton, primaryButton, uiText } from "../styles.js";
import { useAction } from "../hooks/useAction.js";

import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { ConfigLocationCard, RestoreResult } from "./ConfigLocationCard.jsx";
import { FolderPicker } from "./FolderPicker.jsx";

// Farmhand's settings copy on the NAS: Save all, Load all settings, where it goes, and what to do when the folder chosen
// already holds one. initialInfo: its location as the Storage page loaded it. shares: the connected network
// shares, to pick a folder on. onSettingsRestored: the look and preferences came back. reloadAll: the Storage page
// reloads (a restore can bring back shares and folders).
export function SettingsCopy({ initialInfo, shares, onSettingsRestored, reloadAll }) {
  const [configInfo, setConfigInfo] = useState(initialInfo); // where the settings copy goes
  const [configPicker, setConfigPicker] = useState(null); // null | "choose" | "load" (a folder to load settings from)
  const [saved, setSaved] = useState(null); // where the last Save all wrote everything
  const [saving, setSaving] = useState(false);
  const [configFound, setConfigFound] = useState(null); // the folder just chosen already holds a settings file
  const [configRestoreOpen, setConfigRestoreOpen] = useState(false);
  const [configResult, setConfigResult] = useState(null);
  const { busy: configBusy, error: configError, setError: setConfigError, run } = useAction();

  const chooseConfigFolder = async (path) => {
    setConfigError(null);
    setSaved(null);
    const found = await inspectConfigFolder(path); // refuses (with the reason) a folder that can't be used
    if (found.fileExists) {
      setConfigFound(found); // never overwrite settings that are already there without being told to
      return;
    }
    if (configPicker === "load") throw new Error("There are no saved Farmhand settings in that folder. Pick the folder they were saved in.");
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
  // Save all: everything written to the settings folder now (Farmhand picks "farmhand configs" when none is chosen)
  const saveAll = async () => {
    setConfigError(null);
    setSaved(null);
    setSaving(true);
    try {
      const r = await saveAllSettings();
      if (r.needsChoice) {
        setConfigFound(r.found); // that folder already has settings: ask before replacing them
      } else {
        setConfigInfo(r.location);
        if (r.mirror && !r.mirror.ok) setConfigError(r.mirror.error);
        else setSaved(r.location.path);
      }
    } catch (e) {
      setConfigError(errorText(e));
    } finally {
      setSaving(false);
    }
  };
  // Load all settings: from the settings folder (asked first), or, with none chosen or nothing saved there yet, from
  // a folder picked where they were saved
  const loadAll = () => {
    setConfigError(null);
    setSaved(null);
    if (configInfo?.isSet && configInfo.file?.exists) setConfigRestoreOpen(true);
    else setConfigPicker("load");
  };

  return (
    <>
      <ConfigLocationCard
        info={configInfo}
        error={configError}
        onChoose={() => setConfigPicker("choose")}
        onSaveAll={saveAll}
        onLoadAll={loadAll}
        onClear={clearConfigFolder}
        saving={saving}
        saved={saved}
      />
      {configResult && <RestoreResult result={configResult} />}

      {configPicker && (
        <FolderPicker
          title={configPicker === "load" ? "Choose the folder your settings were saved in" : "Choose the folder for Farmhand's settings"}
          startPath={configInfo?.isSet ? configInfo.path : null}
          shares={shares}
          onSelect={chooseConfigFolder}
          onClose={() => setConfigPicker(null)}
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
          title="Load all settings"
          confirmLabel="Load all"
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
            Load all the settings saved in <b style={{ color: c.heading }}>{configInfo?.path}</b>? The look, the arrangements of
            the Printers, Monitor and Farm cost pages and the Power page's electricity prices are replaced with the saved ones;
            the STL, 3MF, project and farm cost folders it lists are put back; network shares and printers that aren't here
            yet are added, and what printers and models are missing is filled in. A share's password isn't saved, so a share
            added back needs its password typed in.
          </div>
        </ConfirmDialog>
      )}
    </>
  );
}
