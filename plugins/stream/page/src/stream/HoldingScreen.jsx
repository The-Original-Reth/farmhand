import { c } from "../theme.js";
import { streamPictureUrl } from "../api.js";
import { fieldBox, primaryButton, uiText } from "../styles.js";
import { ColourPick, FontPick, panelRow, panelSwatch } from "./controls.jsx";
import { fontFamily } from "./shapes.js";
import { heading, help, panel } from "./streamStyles.js";

// The holding screen: what YouTube is shown for about a minute after the Stream plugin's own restart (an update, a
// reboot), while the delay fills again behind it, so the broadcast never goes without video. Its words, a picture from
// the stream folder, and its colours and font (each left empty: the stream's own). Saved with its own Save (`onSave`:
// just the holding screen, anything else changed on the page stays to be saved) or with the page's Save.
// The preview draws it as the stream does (services: live_stream/holding.py): the picture fitted in the box at the top,
// the words centred under it, each line centred (or in the middle with no picture).
const PICTURE_BOX = { left: "10%", top: "8%", width: "80%", height: "56%" };
const WORDS_UNDER = "79%";
const WORDS_ALONE = "50%";
const WORDS_SIZE = 0.09 * (9 / 16) * 100; // 9% of the height, in parts of the width (cqw)


export function HoldingScreenPanel({ shown, change, media, fonts, saved, onSave, busy }) {
  const holding = shown.holding;
  const dirty = JSON.stringify(holding) !== JSON.stringify(saved);
  const set = (what) => change({ holding: { ...holding, ...what } });
  const background = holding.background || shown.background || "#000000";
  const color = holding.color || shown.color || "#FFFFFF";
  const font = holding.font || shown.font;
  const images = media?.images || [];

  const colour = (name, value, fallback, what) => (
    <ColourPick
      testid={`holding-${name}`} value={value} onPick={(v) => set({ [name]: v })} fallback={fallback}
      reset={{ label: "The stream's" }} labelStyle={panelRow} swatch={panelSwatch}
    >
      {what} <span style={uiText(11, c.textFaint)}>{value || `${fallback} · the stream's`}</span>
    </ColourPick>
  );

  return (
    <div data-testid="stream-holding" style={panel()}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ ...heading, flex: 1 }}>Holding screen</div>
        <span style={uiText(12, dirty ? c.amber : c.textFaint)}>{dirty ? "Not saved yet" : "Saved"}</span>
        <button type="button" data-testid="holding-save" onClick={onSave} disabled={!dirty || !!busy} style={primaryButton(!dirty || !!busy)}>
          {busy === "holding" ? "Saving…" : "Save"}
        </button>
      </div>
      <div style={help}>
        Shown on YouTube for about a minute after the Stream plugin restarts (an update or a reboot), while the delay fills
        again behind it. YouTube keeps getting video, so the broadcast carries on, and then switches to the cameras.
      </div>

      <div
        data-testid="holding-preview"
        style={{ position: "relative", width: "100%", aspectRatio: "16 / 9", background, overflow: "hidden", containerType: "inline-size", border: `1px solid ${c.border}` }}
      >
        {holding.image && (
          <img
            alt="" src={streamPictureUrl(holding.image)}
            style={{ position: "absolute", ...PICTURE_BOX, objectFit: "contain" }}
          />
        )}
        {holding.text.trim() && (
          <div
            style={{
              position: "absolute", left: 0, right: 0, top: holding.image ? WORDS_UNDER : WORDS_ALONE, transform: "translateY(-50%)",
              textAlign: "center", whiteSpace: "pre-line", color, fontFamily: fontFamily(font), fontSize: `${WORDS_SIZE}cqw`, lineHeight: 1.25,
            }}
          >
            {holding.text}
          </div>
        )}
      </div>

      <label style={uiText(13, c.textPrimary, { display: "flex", flexDirection: "column", gap: 6 })}>
        Words
        <textarea
          data-testid="holding-text" value={holding.text} rows={2} maxLength={300} onChange={(e) => set({ text: e.target.value })}
          style={{ ...fieldBox(), padding: "6px 8px", resize: "vertical", fontFamily: "inherit" }}
        />
      </label>
      <label style={panelRow}>
        Picture
        <select data-testid="holding-image" value={holding.image || ""} onChange={(e) => set({ image: e.target.value || null })} style={{ ...fieldBox(), padding: "5px 8px" }}>
          <option value="">None</option>
          {images.map((name) => <option key={name} value={name}>{name}</option>)}
          {holding.image && !images.includes(holding.image) && <option value={holding.image}>{holding.image} (not in the stream folder)</option>}
        </select>
        {!images.length && <span style={uiText(11, c.textFaint)}>add pictures to the stream folder's images to choose one</span>}
      </label>
      <label style={panelRow}>
        Font
        <FontPick testid="holding-font" value={holding.font} onPick={(v) => set({ font: v })} fonts={fonts} fallback={shown.font} defaultLabel="The stream's" />
      </label>
      {colour("color", holding.color, shown.color || "#FFFFFF", "Words")}
      {colour("background", holding.background, shown.background || "#000000", "Background")}
    </div>
  );
}
