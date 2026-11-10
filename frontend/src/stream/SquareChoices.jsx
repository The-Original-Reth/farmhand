import { c } from "../theme.js";
import { headerButton, uiText } from "../styles.js";
import { box, colourBox, help, label12 } from "./editorFields.js";
import { FULL_BOX, MIDDLE, fontFamily } from "./CardScreen.jsx";

// What a camera square and a card's words can be set to, in the square editor (SquareEditor.jsx).

// A camera: one in another square moves here
export function CameraChoice({ cells, i, onCells, cameras, label }) {
  const cell = cells[i];
  const placed = new Set(cells.filter((x) => x?.camera).map((x) => x.camera));
  const pick = (key) => onCells(cells.map((x, j) => (j === i ? (key ? { ...(x?.camera ? x : {}), camera: key } : null) : x?.camera === key ? null : x)));
  return (
    <select data-testid="stream-square-camera" value={cell?.camera || ""} onChange={(e) => pick(e.target.value)} style={box()}>
      <option value="">Choose a camera…</option>
      {cell?.camera && !cameras.some((x) => x.key === cell.camera) && <option value={cell.camera}>{label(cell.camera)} (not found)</option>}
      {cameras.map((x) => (
        <option key={x.key} value={x.key}>{x.label}{placed.has(x.key) && cell?.camera !== x.key ? " (moves here)" : ""}</option>
      ))}
    </select>
  );
}

// a font list whose first choice is the stream's own (Defaults, on the right); "" chooses it
function FontPick({ testid, value, onPick, fonts, streamText }) {
  const usual = fonts.find((f) => f.key === (streamText.font || "play"))?.label || "Play";
  return (
    <select data-testid={testid} value={value || ""} onChange={(e) => onPick(e.target.value || null)} style={{ ...box(), fontFamily: fontFamily(value || streamText.font) }}>
      <option value="">Default ({usual})</option>
      {fonts.map((f) => (
        <option key={f.key} value={f.key} style={{ fontFamily: fontFamily(f.key) }}>{f.label}</option>
      ))}
    </select>
  );
}

// a colour that's the stream's own (Defaults, on the right) until one is picked; Default goes back to it
function ColourPick({ testid, value, onPick, streamText, label }) {
  return (
    <label style={label12}>
      <input type="color" data-testid={testid} value={(value || streamText.color || "#FFFFFF").toLowerCase()} onChange={(e) => onPick(e.target.value.toUpperCase())} style={colourBox} />
      {label}
      {value ? (
        <button type="button" onClick={() => onPick(null)} style={headerButton()} title="Use the stream's default colour (Defaults, on the right)">
          Default
        </button>
      ) : (
        <span style={uiText(11, c.textFaint)}>(default)</span>
      )}
    </label>
  );
}

// The printer's name and print written on a camera: shown or not, and their font, colour and size (Automatic: sized to the
// square, as on every camera). Only what differs from the usual is kept on the square.
export function CameraWordsChoice({ cell, put, fonts, showStatus, streamText }) {
  const set = (what) => {
    const next = { ...cell, ...what };
    for (const [k, usual] of [["show_words", true], ["words_size", null], ["words_color", null], ["words_font", null]]) {
      if (next[k] === usual || next[k] === undefined) delete next[k];
    }
    put(next);
  };
  const shown = cell.show_words !== false;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: `1px solid ${c.border}`, paddingTop: 8 }}>
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8 })}>
        <input data-testid="stream-camera-words" type="checkbox" checked={shown} onChange={(e) => set({ show_words: e.target.checked })} />
        Write the printer's name and print on this camera
      </label>
      {!showStatus && <div style={help}>Turned off for every camera in Defaults (on the right): turn it on there to see them.</div>}
      {shown && (
        <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
          <label style={label12}>
            Font
            <FontPick testid="stream-camera-words-font" value={cell.words_font} onPick={(v) => set({ words_font: v })} fonts={fonts} streamText={streamText} />
          </label>
          <ColourPick testid="stream-camera-words-color" value={cell.words_color} onPick={(v) => set({ words_color: v })} streamText={streamText} label="Colour" />
          <label style={label12}>
            Size
            <input
              data-testid="stream-camera-words-size" type="range" min={2} max={30} value={Math.round((cell.words_size || 0.056) * 100)}
              onChange={(e) => set({ words_size: Number(e.target.value) / 100 })}
            />
            <span style={uiText(11, c.textFaint)}>{cell.words_size ? `${Math.round(cell.words_size * 100)}%` : "Automatic"}</span>
          </label>
          {cell.words_size && (
            <button type="button" onClick={() => set({ words_size: null })} style={headerButton()} title="Sized to the square, as on every camera">
              Automatic size
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Words over the square, if you like: what they say, their font, colour and size (also set by dragging on the canvas)
export function TextChoice({ card, setCard, fonts, streamText }) {
  const tb = card.text_box || MIDDLE;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: `1px solid ${c.border}`, paddingTop: 8 }}>
      <div style={uiText(12, c.textMuted)}>Text <span style={uiText(11, c.textFaint)}>(leave empty for none · {card.text.length}/500)</span></div>
      <textarea
        data-testid="stream-square-text" value={card.text} maxLength={500} rows={2} placeholder="Words to show on this square"
        onChange={(e) => setCard({ text: e.target.value })} style={{ ...box(), resize: "vertical", lineHeight: 1.4 }}
      />
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
        <label style={label12}>
          Font
          <FontPick testid="stream-square-font" value={card.font} onPick={(v) => setCard({ font: v })} fonts={fonts} streamText={streamText} />
        </label>
        <ColourPick testid="stream-square-color" value={card.color} onPick={(v) => setCard({ color: v })} streamText={streamText} label="Text colour" />
        <label style={label12} title="A dark band behind the words, so they can be read over a busy picture">
          <input data-testid="stream-square-band" type="checkbox" checked={!!card.band} onChange={(e) => setCard({ band: e.target.checked })} />
          Dark band behind it
        </label>
        <label style={label12}>
          Size
          <input
            data-testid="stream-square-text-size" type="range" min={2} max={60} value={Math.round(tb.size * 100)}
            onChange={(e) => setCard({ text_box: { ...tb, size: Number(e.target.value) / 100 } })}
          />
        </label>
        <button type="button" onClick={() => setCard({ text_box: { ...tb, x: 0.5, y: 0.5 } })} style={headerButton()}>
          Centre text
        </button>
        {card.text && (
          <button type="button" data-testid="stream-square-delete-text" onClick={() => setCard({ text: "" })} style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}>
            Delete text
          </button>
        )}
        {(card.image || card.slideshow) && (
          <button type="button" data-testid="stream-square-fill" onClick={() => setCard({ picture_box: FULL_BOX })} style={headerButton()}>
            Picture fills the square
          </button>
        )}
      </div>
    </div>
  );
}
