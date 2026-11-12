import { useRef, useState } from "react";
import { Image, Trash2, Type } from "lucide-react";
import { c } from "../theme.js";
import { headerButton, uiText } from "../styles.js";
import { uploadStreamPictures } from "../api.js";
import { box, help, label12 } from "./streamStyles.js";
import { ColourPick, FontPick, fontLabel } from "./controls.jsx";
import { MAX_LAYERS, isBlank, layersChange, layersOf, newPicture, newText, slideLabel } from "./shapes.js";

// More pictures and words on the square being edited, right under its canvas: any card (a slideshow's, on the screen on
// show, `slideName`, each screen keeping its own). Each is placed on its own on the canvas (dragged to move, by its corner to resize). Add picture
// (one of the stream folder's pictures, or a new one uploaded), Add text, the list of what's there (click one to
// choose it, here or on the canvas), and the chosen one's own choices; Delete takes one off. Saved with Save.
// `layer`, `setLayer`: the one chosen (its place in the list).
export function LayersChoice({ card, setCard, media, slideName, fonts, streamText, ask, busy, layer, setLayer }) {
  const input = useRef(null);
  const [adding, setAdding] = useState(false); // choosing the picture to add
  const layers = layersOf(card, slideName) || [];
  const set = (next) => setCard(layersChange(card, slideName, next));
  const full = layers.length >= MAX_LAYERS;
  const add = (l) => {
    set([...layers, l]);
    setLayer(layers.length);
    setAdding(false);
  };
  const change = (i, what) => set(layers.map((l, j) => (j === i ? { ...l, ...what } : l)));
  const remove = (i) => {
    set(layers.filter((_, j) => j !== i));
    setLayer(null);
  };
  const upload = async (files) => {
    if (!files.length) return;
    const before = new Set(media.images);
    const p = await ask("picture", () => uploadStreamPictures(files));
    input.current.value = "";
    const added = p?.media.images.find((n) => !before.has(n));
    if (added) add(newPicture(added));
  };
  const chosen = layer !== null ? layers[layer] : null;
  const usual = fontLabel(fonts, streamText.font);
  const where = card.slideshow ? (isBlank(slideName) ? slideLabel(slideName).toLowerCase() : `this picture (${slideName})`) : "this square";

  return (
    <div data-testid="stream-layers" style={{ display: "flex", flexDirection: "column", gap: 6, border: `1px solid ${c.border}`, borderRadius: 4, padding: 8, marginTop: 4 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <span style={uiText(12, c.heading, { fontWeight: 600, marginRight: 4 })}>
          Pictures and text on {where} <span style={uiText(11, c.textFaint, { fontWeight: 400 })}>({layers.length}/{MAX_LAYERS})</span>
        </span>
        <button type="button" data-testid="stream-layer-add-picture" onClick={() => setAdding(!adding)} disabled={full} style={{ ...headerButton(), color: adding ? c.amber : c.textMuted }}>
          <Image size={13} /> Add picture
        </button>
        <button type="button" data-testid="stream-layer-add-text" onClick={() => add(newText())} disabled={full} style={headerButton()}>
          <Type size={13} /> Add text
        </button>
      </div>
      {adding && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <select data-testid="stream-layer-picture-pick" value="" onChange={(e) => e.target.value && add(newPicture(e.target.value))} style={box()}>
            <option value="">{media.images.length ? "Choose a picture…" : "No pictures yet"}</option>
            {media.images.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <input ref={input} type="file" multiple accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => upload([...e.target.files])} />
          <button type="button" onClick={() => input.current.click()} disabled={!!busy || !!media.error} style={headerButton()}>
            {busy === "picture" ? "Uploading…" : "Upload picture"}
          </button>
          <button type="button" onClick={() => setAdding(false)} style={headerButton()}>
            Cancel
          </button>
        </div>
      )}
      {layers.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {layers.map((l, i) => (
            <div
              key={i} data-testid="stream-layer" onClick={() => setLayer(layer === i ? null : i)}
              style={{
                display: "flex", alignItems: "center", gap: 6, padding: "2px 6px", borderRadius: 3, cursor: "pointer",
                background: layer === i ? c.amberDim : "transparent", border: `1px solid ${layer === i ? c.amberBorder : "transparent"}`,
              }}
            >
              {l.type === "picture" ? <Image size={13} color={c.textMuted} /> : <Type size={13} color={c.textMuted} />}
              <span style={uiText(12, layer === i ? c.heading : c.textMuted, { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>
                {l.type === "picture" ? l.image || "(no picture chosen)" : l.text.trim().split("\n")[0] || "(no words yet)"}
              </span>
              <button
                type="button" data-testid="stream-layer-delete" aria-label="Delete" title="Take it off" onClick={(e) => (e.stopPropagation(), remove(i))}
                style={{ ...headerButton(), padding: "0 6px", color: c.danger, borderColor: c.border }}
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      {chosen?.type === "picture" && (
        <label style={label12}>
          Picture
          <select data-testid="stream-layer-picture" value={chosen.image || ""} onChange={(e) => change(layer, { image: e.target.value || null })} style={box()}>
            <option value="">Choose a picture…</option>
            {chosen.image && !media.images.includes(chosen.image) && <option value={chosen.image}>{chosen.image} (not in the folder)</option>}
            {media.images.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      )}
      {chosen?.type === "text" && (
        <>
          <textarea
            data-testid="stream-layer-text" value={chosen.text} maxLength={500} rows={2} placeholder="Its words"
            onChange={(e) => change(layer, { text: e.target.value })} style={{ ...box(), resize: "vertical", lineHeight: 1.4 }}
          />
          <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
            <label style={label12}>
              Font
              <FontPick
                testid="stream-layer-font" value={chosen.font} onPick={(v) => change(layer, { font: v })} fonts={fonts}
                fallback={streamText.font} defaultLabel={`Default (${usual})`}
              />
            </label>
            <ColourPick testid="stream-layer-color" value={chosen.color} onPick={(v) => change(layer, { color: v })} fallback={streamText.color || "#FFFFFF"}>
              Colour
            </ColourPick>
            <label style={label12}>
              <input type="checkbox" checked={!!chosen.band} onChange={(e) => change(layer, { band: e.target.checked })} />
              Dark band behind it
            </label>
            <label style={label12}>
              Size
              <input
                type="range" min={2} max={60} value={Math.round(chosen.box.size * 100)}
                onChange={(e) => change(layer, { box: { ...chosen.box, size: Number(e.target.value) / 100 } })}
              />
            </label>
          </div>
        </>
      )}
      <div style={help}>
        {layers.length
          ? "Click one to change it (here or on the canvas); drag it on the canvas to move it, and by its corner to resize it."
          : "Add as many pictures and pieces of text as you like, each placed where you want it."}
      </div>
    </div>
  );
}
