import { useEffect, useState } from "react";
import { HardDrive } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { errorText, getStreamLocation, setStreamLocation } from "../api.js";
import { monoText, panelBox, uiText } from "../styles.js";

import { Badge } from "../components/common/ui.jsx";
import { locationProblem } from "./ConfigLocationCard.jsx";
import { FolderPicker } from "./FolderPicker.jsx";

// Where the Stream page's pictures are kept: by default a "stream" folder in the folder above the STL / OBJ / STEP folder
// (beside "farm-cost"), or one chosen here (it gets Farmhand's marker, so a share that isn't mounted is never written
// under). Single pictures go in its "images" folder, each slideshow in a folder of its own in "slideshows".
export function StreamFolderCard({ shares }) {
  const [info, setInfo] = useState(null);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState(null);
  const btn = { ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.borderStrong}`, borderRadius: 4, padding: "6px 12px", cursor: "pointer" };

  useEffect(() => {
    getStreamLocation().then(setInfo, (e) => setError(errorText(e)));
  }, []);

  const choose = async (path) => {
    setError(null);
    try {
      setInfo(await setStreamLocation(path));
    } catch (e) {
      setError(errorText(e));
    }
  };

  if (!info) return error ? <div style={uiText(12, c.amber)}>Couldn't load the stream folder: {error}</div> : null;
  const problem = info.status.ready ? null : info.isDefault ? "The STL folder isn't available" : locationProblem(info.status);
  return (
    <div data-testid="stream-folder-card" style={panelBox({ padding: 16 })}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div style={uiText(15, c.heading)}>Stream pictures</div>
        <div style={{ display: "flex", gap: 6 }}>
          <Badge tone={info.isDefault ? "muted" : "teal"}>{info.isDefault ? "default location" : "chosen location"}</Badge>
          {problem ? <Badge tone="amber">{problem}</Badge> : <Badge tone="green">ready</Badge>}
        </div>
      </div>
      <div style={uiText(12, c.textFaint, { marginBottom: 12, lineHeight: 1.5 })}>
        The Stream page's pictures: single ones in its "images" folder, and each slideshow a folder of its own in "slideshows".
        Pictures you copy in yourself show up too.
        {info.isDefault ? " By default: a \"stream\" folder in the folder above the STL / OBJ / STEP folder." : ""}
        {" "}Pictures already there stay where they are when this changes.
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", border: `1px solid ${c.border}`, borderRadius: 4, background: c.panelAlt, marginBottom: 12 }}>
        <HardDrive size={15} color={c.textFaint} />
        <span data-testid="stream-folder-path" style={monoText(12, c.heading, { wordBreak: "break-all" })}>{info.path}</span>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button data-testid="stream-folder-change" onClick={() => setPicking(true)} style={btn}>
          Change…
        </button>
        {!info.isDefault && (
          <button data-testid="stream-folder-default" onClick={() => choose(null)} style={{ ...btn, color: c.textFaint, borderColor: c.border }}>
            Use default
          </button>
        )}
      </div>
      {error && <div style={uiText(12, c.amber, { marginTop: 10 })}>{error}</div>}
      {picking && (
        <FolderPicker
          title="Folder for the Stream page's pictures"
          startPath={info.path}
          shares={shares}
          onSelect={async (path) => setInfo(await setStreamLocation(path))} // a folder that can't be used: the picker says why
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}
