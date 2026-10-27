import { useState } from "react";
import { c, fs, mono, ui } from "../theme.js";
import { uiText } from "../styles.js";
import { errorText, redrawPreview } from "../api.js";
import { useData } from "../data.jsx";

// Previews drawn by older versions of Farmhand (the first one thinned detailed models, leaving them
// see-through) are redrawn from their files, one at a time so progress shows.
export function RedrawPreviewsDialog({ onClose }) {
  const { sourceModels, refresh } = useData();
  const targets = sourceModels.filter((m) => m.type === "STL" && m.versions.length > 0);
  const [phase, setPhase] = useState("confirm"); // confirm | running | done
  const [done, setDone] = useState(0);
  const [result, setResult] = useState(null);

  const run = async () => {
    setPhase("running");
    setDone(0);
    let redrawn = 0;
    let skipped = 0;
    const failed = [];
    for (let i = 0; i < targets.length; i += 1) {
      const m = targets[i];
      try {
        const r = await redrawPreview({ modelId: m.id, version: m.versions[0].v }); // the newest version is what the list shows
        if (r.updated) redrawn += 1;
        else skipped += 1;
      } catch (e) {
        failed.push({ name: m.name, error: errorText(e) });
      }
      setDone(i + 1);
    }
    await refresh().catch(() => {}); // the redrawn previews come back with new addresses (?r=), so they show
    setResult({ redrawn, skipped, failed });
    setPhase("done");
  };

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const button = (label, onClick, primary, extra = {}) => (
    <button
      onClick={onClick}
      style={{ ...ui, fontSize: fs(13), background: primary ? c.amber : "none", color: primary ? c.onAccent : c.textMuted, border: primary ? "none" : `1px solid ${c.border}`, borderRadius: 3, padding: "7px 14px", fontWeight: primary ? 600 : 400, cursor: "pointer", ...extra }}
    >
      {label}
    </button>
  );

  if (phase === "running") {
    return (
      <div data-testid="redraw-progress">
        <div style={uiText(13, c.textMuted, { marginBottom: 10 })}>
          Redrawing {Math.min(done + 1, targets.length)} of {targets.length}…
        </div>
        <div style={{ height: 6, borderRadius: 3, background: c.panelAlt, overflow: "hidden" }}>
          <div style={{ width: `${targets.length ? (done / targets.length) * 100 : 0}%`, height: "100%", background: c.amber, transition: "width 0.2s ease" }} />
        </div>
      </div>
    );
  }
  if (phase === "done") {
    return (
      <div data-testid="redraw-summary">
        <div style={uiText(14, c.heading, { marginBottom: 8 })}>
          Redrew {plural(result.redrawn, "preview", "previews")}.
        </div>
        {result.skipped > 0 && (
          <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 8 })}>
            {plural(result.skipped, "file couldn't be drawn", "files couldn't be drawn")} (not a readable STL) and were left as they were.
          </div>
        )}
        {result.failed.length > 0 && (
          <div style={uiText(12, c.amber, { lineHeight: 1.6, marginBottom: 8 })}>
            {plural(result.failed.length, "preview couldn't be redrawn", "previews couldn't be redrawn")}:
            {result.failed.map((f) => (
              <div key={f.name}>
                <span style={mono}>{f.name}</span> — {f.error}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>{button("Done", onClose, false)}</div>
      </div>
    );
  }
  return (
    <>
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 14 })}>
        Redraw the previews of <b style={{ color: c.heading }}>{plural(targets.length, "STL model", "STL models")}</b> from their files.
        Use this after an update that improves how previews are drawn — earlier ones of detailed models can look thin or
        see-through. Your files aren't changed, and a preview that can't be redrawn is left as it was.
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        {button("Cancel", onClose, false)}
        <span data-testid="redraw-start">
          {button(`Redraw ${plural(targets.length, "preview", "previews")}`, run, true, {
            opacity: targets.length === 0 ? 0.5 : 1,
            pointerEvents: targets.length === 0 ? "none" : "auto",
          })}
        </span>
      </div>
    </>
  );
}
