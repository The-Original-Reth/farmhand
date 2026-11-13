import { useEffect, useState } from "react";
import { c, fs, mono, ui } from "../theme.js";
import { errorText, getConfig, getShares, getStorageSettings, migrateStorage, saveStorageSettings, setFarmCostLocation } from "../api.js";
import { uiText } from "../styles.js";

import { ConfirmDialog } from "../components/common/dialogs.jsx";
import { plural } from "../lib/format.js";
import { FolderPicker } from "./FolderPicker.jsx";
import { useSettingsCopy } from "./useSettingsCopy.jsx";
import { SaveLocationCard } from "./SaveLocationCard.jsx";
import { PluginSettings, SettingsHeading } from "../plugins/PluginSettings.jsx";

// Files still in a folder used before (the save location or a folder changed since), and Move them now…
function OutsideFiles({ counts: { outsideStl, outsideThreemf, outsideProject, outsideAll }, onMove }) {
  return (
    <div style={{ border: `1px solid ${c.borderStrong}`, borderRadius: 4, background: c.panelAlt, padding: 16 }}>
      <div style={uiText(13, c.textPrimary, { marginBottom: 6 })}>
        {[
          outsideStl > 0 && plural(outsideStl, "STL version", "STL versions"),
          outsideThreemf > 0 && plural(outsideThreemf, "3MF version", "3MF versions"),
          outsideProject > 0 && plural(outsideProject, "project file version", "project file versions"),
        ]
          .filter(Boolean)
          .join(" and ")}{" "}
        still {outsideAll === 1 ? "has" : "have"} files in a previous location.
      </div>
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
        They keep working where they are — only new uploads go to the save location. Moving copies each file into its
        folder there, checks the copy, and only then removes the original.
      </div>
      <button
        onClick={onMove}
        style={{ ...ui, fontSize: fs(13), background: c.amber, color: c.onAccent, border: "none", borderRadius: 4, padding: "7px 14px", fontWeight: 600, cursor: "pointer" }}
      >
        Move them now…
      </button>
    </div>
  );
}

// What Move them now did
function MoveResult({ result }) {
  return (
    <div data-testid="move-result" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 14, ...ui, fontSize: fs(13), color: c.textMuted, lineHeight: 1.6 }}>
      Moved {plural(result.movedStl, "STL version", "STL versions")},{" "}
      {plural(result.movedThreemf, "3MF version", "3MF versions")} and{" "}
      {plural(result.movedProject, "project file version", "project file versions")}.
      {result.missing.length > 0 && (
        <div style={{ color: c.amber, marginTop: 6 }}>
          Not found on disk (skipped): <span style={mono}>{result.missing.join(", ")}</span>
        </div>
      )}
      {result.failed.map((f) => (
        <div key={f.name} style={{ color: c.amber, marginTop: 6 }}>
          Couldn't move <span style={mono}>{f.name}</span>: {f.error}
        </div>
      ))}
    </div>
  );
}

export function StorageSection({ onSettingsRestored, plugins = [], onOpenPluginPage, onOpenPlugins }) {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [picker, setPicker] = useState(null); // null | "stl" | "threemf" | "project"
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveResult, setMoveResult] = useState(null);
  const [sharesInfo, setSharesInfo] = useState(null);
  const [configInfo, setConfigInfo] = useState(null); // where the settings copy goes, as first loaded
  const [folderChanges, setFolderChanges] = useState(0); // a folder was changed: the save location's list reads them again

  useEffect(() => {
    Promise.all([getStorageSettings(), getShares(), getConfig().catch(() => null)])
      .then(([storageInfo, sharesData, config]) => {
        setInfo(storageInfo);
        setSharesInfo(sharesData);
        setConfigInfo(config ? config.location : null);
      })
      .catch((e) => setError(errorText(e)));
  }, []);

  // Shares and the storage locations affect each other (a share's files, what's "ready"), so refresh both
  const reloadAll = async () => {
    const [storageInfo, sharesData] = await Promise.all([getStorageSettings(), getShares()]);
    setInfo(storageInfo);
    setSharesInfo(sharesData);
  };
  const copy = useSettingsCopy({ initialInfo: configInfo, shares: sharesInfo?.shares || [], onSettingsRestored, reloadAll });
  useEffect(() => setFolderChanges((n) => n + 1), [copy.info?.path, copy.info?.isSet]); // (the settings folder changed)

  if (error) {
    return <div style={uiText(13, c.amber)}>Couldn't load storage settings: {error}</div>;
  }
  if (!info || !sharesInfo) {
    return <div style={uiText(13, c.textFaint)}>Loading storage settings…</div>;
  }

  const body = (kind, path) => ({ [{ stl: "stlPath", threemf: "threemfPath", project: "projectPath" }[kind]]: path });
  const outsideStl = info.outside.stl;
  const outsideThreemf = info.outside.threemf;
  const outsideProject = info.outside.project || 0;
  const outsideAll = outsideStl + outsideThreemf + outsideProject;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 820 }}>
      {/* Farmhand's own settings first, under its name; then each plugin's, under the plugin's name (PluginSettings) */}
      <SettingsHeading>Farmhand</SettingsHeading>
      {/* The save location: one place on the NAS for everything, then Save all and Load all settings */}
      <SaveLocationCard
        shares={sharesInfo.shares}
        copy={copy}
        refresh={folderChanges}
        onChangeFolder={(key) => (key === "config" ? copy.choose() : setPicker(key))}
        onSaved={async (r) => {
          await reloadAll();
          await copy.reloadInfo();
          if (r.configChoice) copy.offerFound(r.configChoice); // settings already saved there: load or replace them?
        }}
      />
      {copy.result}

      {outsideAll > 0 && <OutsideFiles counts={{ outsideStl, outsideThreemf, outsideProject, outsideAll }} onMove={() => setMoveOpen(true)} />}
      {moveResult && <MoveResult result={moveResult} />}

      <div style={uiText(12, c.textFaint, { lineHeight: 1.7 })}>
        <div>
          <b style={{ color: c.textMuted }}>Safety check.</b> Chosen folders get a small <span style={mono}>.farmhand-storage</span>{" "}
          marker. If a share drops and leaves an empty folder behind, the marker is missing and uploads are refused rather
          than silently filling the local disk.
        </div>
        <div style={{ marginTop: 6 }}>
          <b style={{ color: c.textMuted }}>Previews</b> are saved next to each STL, 3MF and CAD file (Frog.stl gets Frog.stl.png),
          so they're on the NAS with their files, and only there: while a share is offline, its previews don't show.
        </div>
      </div>
      {copy.dialogs}


      {picker && (
        <FolderPicker
          title={`Choose the folder for ${{ stl: "STL files", threemf: "3MF files", project: "project files", farmCost: "the farm cost records" }[picker]}`}
          startPath={picker === "farmCost" ? null : info[picker].isDefault ? null : info[picker].path}
          shares={sharesInfo.shares}
          onSelect={async (path) => {
            // (a folder that can't be used: the picker says why)
            if (picker === "farmCost") await setFarmCostLocation(path);
            else setInfo(await saveStorageSettings(body(picker, path)));
            setFolderChanges((n) => n + 1);
          }}
          onClose={() => setPicker(null)}
        />
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

      <PluginSettings plugins={plugins} onOpenPage={onOpenPluginPage} onOpenPlugins={onOpenPlugins} />
    </div>
  );
}
