import { useEffect, useState } from "react";
import { HardDrive } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { errorText, getFarmCostLocation, setFarmCostLocation } from "../api.js";
import { monoText, panelBox, uiText } from "../styles.js";

import { Badge } from "../components/common/ui.jsx";
import { locationProblem } from "./ConfigLocationCard.jsx";
import { FolderPicker } from "./FolderPicker.jsx";

// Where each month's Farm cost record is saved once the month is over: by default a "farm cost" folder in the folder
// above the STL / OBJ / STEP folder, or one chosen here (it gets Farmhand's marker, so a share that isn't mounted is
// never written under). Records already saved stay where they are.
export function FarmCostFolderCard({ shares }) {
  const [info, setInfo] = useState(null);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState(null);
  const btn = { ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.borderStrong}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" };

  useEffect(() => {
    getFarmCostLocation().then(setInfo, (e) => setError(errorText(e)));
  }, []);

  const choose = async (path) => {
    setError(null);
    try {
      setInfo(await setFarmCostLocation(path));
    } catch (e) {
      setError(errorText(e));
    }
  };

  if (!info) return error ? <div style={uiText(12, c.amber)}>Couldn't load the farm cost folder: {error}</div> : null;
  const problem = info.status.ready ? null : info.isDefault ? "The STL folder isn't available" : locationProblem(info.status);
  return (
    <div data-testid="farm-cost-folder-card" style={panelBox({ padding: 16 })}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div style={uiText(15, c.heading)}>Farm cost records</div>
        <div style={{ display: "flex", gap: 6 }}>
          <Badge tone={info.isDefault ? "muted" : "teal"}>{info.isDefault ? "default location" : "chosen location"}</Badge>
          {problem ? <Badge tone="amber">{problem}</Badge> : <Badge tone="green">ready</Badge>}
        </div>
      </div>
      <div style={uiText(12, c.textFaint, { marginBottom: 12, lineHeight: 1.5 })}>
        When a month ends, its Farm cost table is saved here as a CSV (e.g. "farmhand - farm cost - oct 2026.csv").
        {info.isDefault ? " By default: a \"farm cost\" folder in the folder above the STL / OBJ / STEP folder." : ""}
        {" "}Records already saved stay where they are when this changes.
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", border: `1px solid ${c.border}`, borderRadius: 4, background: c.panelAlt, marginBottom: 12 }}>
        <HardDrive size={15} color={c.textFaint} />
        <span data-testid="farm-cost-folder-path" style={monoText(12, c.heading, { wordBreak: "break-all" })}>{info.path}</span>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button data-testid="farm-cost-folder-change" onClick={() => setPicking(true)} style={btn}>
          Change…
        </button>
        {!info.isDefault && (
          <button data-testid="farm-cost-folder-default" onClick={() => choose(null)} style={{ ...btn, color: c.textFaint, borderColor: c.border }}>
            Use default
          </button>
        )}
      </div>
      {error && <div style={uiText(12, c.amber, { marginTop: 10 })}>{error}</div>}
      {picking && (
        <FolderPicker
          title="Folder for the farm cost records"
          startPath={info.path}
          shares={shares}
          onSelect={async (path) => setInfo(await setFarmCostLocation(path))} // a folder that can't be used: the picker says why
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}
