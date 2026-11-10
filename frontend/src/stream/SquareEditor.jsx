import { useEffect, useRef, useState } from "react";
import { c, fixed, fs, ui } from "../theme.js";
import { fieldBox, headerButton, panelBox, primaryButton, uiText } from "../styles.js";
import {
  createSlideshow, removeSlideshow, removeSlideshowPicture, removeStreamPicture, slideshowPictureUrl, streamFontUrl, streamPictureUrl, uploadSlideshowPictures,
  uploadStreamPictures,
} from "../api.js";

// The editor under the preview for the square clicked: the square as a canvas of its own (its shape in the grid), and
// what it shows. Camera (with a colour round it, if you like); Text, Picture or Slideshow (a "card": the square's colour,
// a picture or a slideshow over it, and words over that if you like); or Empty (the stream's background colour). On the
// canvas a card's picture and words are dragged to move them and by their corner to resize them. Pictures are files in
// the stream folder (Settings): single ones in its images folder, each slideshow a folder in its slideshows folder.
// They're uploaded and deleted straight away (`ask`: the page's own way of asking the server); what the square holds is
// saved with Save (here, or the page's).
//
// `cells`, `i`: the grid's squares and the one being edited; `onCells(next)` changes them. `cameras`: [{ key, label }];
// `media`: { images, slideshows: [{ name, images }], error }; `label(key)`: a camera's name; `screen`: a camera square
// drawn as the preview draws it; `aspect`: the square's width over its height; `onSave`, `dirty`, `saving`: saving the
// page now, whether anything isn't saved yet; `onDone` closes the editor.

const KINDS = [["camera", "Camera"], ["text", "Text"], ["picture", "Picture"], ["slideshow", "Slideshow"], ["empty", "Empty"]];
export const kindOf = (cell) => (!cell ? "empty" : cell.camera ? "camera" : cell.slideshow ? "slideshow" : cell.image ? "picture" : "text");
const FULL_BOX = { x: 0, y: 0, w: 1, h: 1 };
const MIDDLE = { x: 0.5, y: 0.5, size: 0.125 };
export const CARD = { background: null, image: null, slideshow: null, seconds: 10, text: "", color: "#FFFFFF", font: "dejavu-sans", band: false, picture_box: FULL_BOX, text_box: MIDDLE };
// the page's own name for one of the stream's fonts (StreamFonts loads each from the server)
export const fontFamily = (key) => `"fh-stream-${key || "dejavu-sans"}", sans-serif`;

// The stream's fonts, loaded from the server so the words look here as they do on the stream: `fonts` [{ key, generic }]
export function StreamFonts({ fonts }) {
  const css = fonts.map((f) => `@font-face { font-family: "fh-stream-${f.key}"; src: url("${streamFontUrl(f.key)}"); font-display: swap; }`).join("\n");
  return <style>{css}</style>;
}
const help = uiText(12, c.textFaint, { lineHeight: 1.5 });
const box = () => ({ ...fieldBox(), padding: "5px 8px" });
const label12 = uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6 });
const colourBox = { width: 30, height: 22, padding: 0, border: `1px solid ${c.border}`, background: "none", cursor: "pointer" };
const clamp = (v, least, most) => Math.round(Math.min(most, Math.max(least, v)) * 1e4) / 1e4;

export function SquareEditor({ cells, i, onCells, cameras, media, fonts = [], showStatus = true, label, screen, aspect = 16 / 9, onDone, onSave, dirty, saving, ask, busy, streamBackground }) {
  const cell = cells[i];
  const [kind, setKind] = useState(kindOf(cell));
  useEffect(() => setKind(kindOf(cells[i])), [i]); // another square clicked
  const card = cell && !cell.camera ? { ...CARD, ...cell } : { ...CARD };
  const put = (next) => onCells(cells.map((x, j) => (j === i ? next : x)));
  const setCard = (what) => put({ ...card, ...what });
  const choose = (k) => {
    setKind(k);
    if (k === "empty") put(null);
    else if (k === "camera") put(cell?.camera ? cell : null);
    else if (k === "text") put({ ...card, image: null, slideshow: null });
    else if (k === "picture") put({ ...card, slideshow: null, image: card.image || media.images[0] || null });
    else put({ ...card, image: null, slideshow: card.slideshow || media.slideshows[0]?.name || null });
  };
  const isCard = ["text", "picture", "slideshow"].includes(kind);
  // the canvas: the square's own shape, no taller than 420 px
  const canvas = { position: "relative", width: "100%", maxWidth: Math.min(640, 420 * aspect), aspectRatio: String(aspect), background: fixed.camera, border: `1px solid ${c.border}`, overflow: "hidden", display: "flex" };
  const ownColour = isCard ? card.background : cell?.camera ? cell.background || null : null;
  const setColour = (v) => (isCard ? setCard({ background: v }) : put(v ? { ...cell, background: v } : { camera: cell.camera }));
  return (
    <div data-testid="stream-square-editor" style={panelBox({ padding: 12, marginTop: 10, display: "flex", flexDirection: "column", gap: 10 })}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <span style={uiText(12, c.textMuted, { marginRight: 4 })}>Square {i + 1}</span>
        {KINDS.map(([k, name]) => (
          <button
            key={k} type="button" data-testid={`stream-square-kind-${k}`} onClick={() => choose(k)}
            style={{ ...headerButton(), color: kind === k ? c.amber : c.textMuted, borderColor: kind === k ? c.amber : c.border }}
          >
            {name}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <span style={uiText(11, dirty ? c.amber : c.textFaint)}>{dirty ? "Not saved yet" : "Saved"}</span>
        <button type="button" data-testid="stream-square-save" onClick={onSave} disabled={!dirty || !!busy} style={primaryButton(!dirty || !!busy)}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onDone} style={headerButton()}>
          Done
        </button>
      </div>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ flex: "1 1 340px", minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
          <div data-testid="stream-square-canvas" style={canvas}>
            {isCard ? <CardScreen card={card} media={media} streamBackground={streamBackground} edit onChange={setCard} /> : screen}
          </div>
          {isCard && (card.text.trim() || card.image || card.slideshow) && (
            <div style={uiText(11, c.textFaint)}>Drag the {card.image || card.slideshow ? "picture or words" : "words"} to move them; drag a corner to make them bigger or smaller.</div>
          )}
        </div>
        <div style={{ flex: "1 1 280px", minWidth: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {kind === "camera" && <CameraChoice cells={cells} i={i} onCells={onCells} cameras={cameras} label={label} />}
          {kind === "picture" && <PictureChoice card={card} setCard={setCard} media={media} ask={ask} busy={busy} />}
          {kind === "slideshow" && <SlideshowChoice card={card} setCard={setCard} media={media} ask={ask} busy={busy} />}
          {(isCard || (kind === "camera" && cell?.camera)) && (
            <label style={label12}>
              <input
                type="color" data-testid="stream-square-colour" value={(ownColour || streamBackground).toLowerCase()}
                onChange={(e) => setColour(e.target.value.toUpperCase())} style={colourBox}
              />
              {kind === "text" ? "Background" : kind === "camera" ? "Colour round the camera" : "Colour round the picture"}
              {ownColour ? (
                <button type="button" onClick={() => setColour(null)} style={headerButton()} title="Use the stream's background colour">
                  Stream's colour
                </button>
              ) : (
                <span style={uiText(11, c.textFaint)}>(the stream's)</span>
              )}
            </label>
          )}
          {isCard && <TextChoice card={card} setCard={setCard} fonts={fonts} />}
          {kind === "camera" && cell?.camera && <CameraWordsChoice cell={cell} put={put} fonts={fonts} showStatus={showStatus} />}
          {kind === "empty" && <div style={help}>Shows the stream's background colour. Choose what the square shows above.</div>}
          {media.error && kind !== "camera" && kind !== "empty" && <div style={uiText(12, c.amber, { lineHeight: 1.5 })}>The stream folder isn't available: {media.error}</div>}
        </div>
      </div>
    </div>
  );
}

// A camera: one in another square moves here
function CameraChoice({ cells, i, onCells, cameras, label }) {
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

// The printer's name and print written on a camera: shown or not, and their font, colour and size (Automatic: sized to the
// square, as on every camera). Only what differs from the usual is kept on the square.
function CameraWordsChoice({ cell, put, fonts, showStatus }) {
  const set = (what) => {
    const next = { ...cell, ...what };
    for (const [k, usual] of [["show_words", true], ["words_size", null], ["words_color", "#FFFFFF"], ["words_font", "dejavu-sans"]]) {
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
      {!showStatus && <div style={help}>Turned off for every camera in Squares (on the right): turn it on there to see them.</div>}
      {shown && (
        <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
          <label style={label12}>
            Font
            <select data-testid="stream-camera-words-font" value={cell.words_font || "dejavu-sans"} onChange={(e) => set({ words_font: e.target.value })} style={{ ...box(), fontFamily: fontFamily(cell.words_font) }}>
              {fonts.map((f) => (
                <option key={f.key} value={f.key} style={{ fontFamily: fontFamily(f.key) }}>{f.label}</option>
              ))}
            </select>
          </label>
          <label style={label12}>
            <input type="color" data-testid="stream-camera-words-color" value={(cell.words_color || "#FFFFFF").toLowerCase()} onChange={(e) => set({ words_color: e.target.value.toUpperCase() })} style={colourBox} />
            Colour
          </label>
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
function TextChoice({ card, setCard, fonts }) {
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
          <select data-testid="stream-square-font" value={card.font || "dejavu-sans"} onChange={(e) => setCard({ font: e.target.value })} style={{ ...box(), fontFamily: fontFamily(card.font) }}>
            {fonts.map((f) => (
              <option key={f.key} value={f.key} style={{ fontFamily: fontFamily(f.key) }}>{f.label}</option>
            ))}
          </select>
        </label>
        <label style={label12}>
          <input type="color" value={card.color.toLowerCase()} onChange={(e) => setCard({ color: e.target.value.toUpperCase() })} style={colourBox} />
          Text colour
        </label>
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

// One of the stream folder's single pictures, or a new one uploaded; Delete picture removes its file
function PictureChoice({ card, setCard, media, ask, busy }) {
  const input = useRef(null);
  const [removing, setRemoving] = useState(false);
  const upload = async (files) => {
    if (!files.length) return;
    const before = new Set(media.images);
    const p = await ask("picture", () => uploadStreamPictures(files));
    input.current.value = "";
    const added = p?.media.images.find((n) => !before.has(n));
    if (added) setCard({ image: added, slideshow: null });
  };
  return (
    <>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <select data-testid="stream-square-picture" value={card.image || ""} onChange={(e) => setCard({ image: e.target.value || null, slideshow: null })} style={box()}>
          <option value="">{media.images.length ? "Choose a picture…" : "No pictures yet"}</option>
          {card.image && !media.images.includes(card.image) && <option value={card.image}>{card.image} (not in the folder)</option>}
          {media.images.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <input ref={input} data-testid="stream-picture-file" type="file" multiple accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => upload([...e.target.files])} />
        <button type="button" data-testid="stream-picture-upload" onClick={() => input.current.click()} disabled={!!busy || !!media.error} style={headerButton()}>
          {busy === "picture" ? "Uploading…" : "Upload picture"}
        </button>
        {card.image && media.images.includes(card.image) && !removing && (
          <button type="button" onClick={() => setRemoving(true)} disabled={!!busy} style={headerButton()}>
            Delete picture
          </button>
        )}
      </div>
      {removing && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <span style={uiText(12, c.textMuted)}>Delete “{card.image}” from the stream folder?</span>
          <button type="button" onClick={() => ask("picture", () => removeStreamPicture(card.image)).then(() => setRemoving(false))} style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}>
            Delete
          </button>
          <button type="button" onClick={() => setRemoving(false)} style={headerButton()}>
            Keep
          </button>
        </div>
      )}
      <div style={help}>PNG, JPEG or WebP, fitted to the square. Pictures copied into the stream folder's images folder show up here too.</div>
    </>
  );
}

// A slideshow (a folder of pictures in the stream folder, shown in turn): chosen from the list, and four buttons. New
// slideshow (asks its name), Add pictures (into the one chosen), Open folder (where its folder is, to open in File
// Explorer) and Delete slideshow. Then how
// long each picture shows, and its pictures, each with its own Delete.
function SlideshowChoice({ card, setCard, media, ask, busy }) {
  const input = useRef(null);
  const [opening, setOpening] = useState(false); // showing where the folder is, for File Explorer
  const [name, setName] = useState(null); // the new slideshow's name being typed; null when not making one
  const [removing, setRemoving] = useState(null); // "show" | a picture's name, asking "Delete?"
  const show = media.slideshows.find((x) => x.name === card.slideshow) || null;
  const create = async () => {
    const n = (name || "").trim();
    if (!n) return;
    const p = await ask("picture", () => createSlideshow(n));
    if (p?.media.slideshows.some((x) => x.name === n)) {
      setCard({ slideshow: n, image: null });
      setName(null);
    }
  };
  const addPictures = async (files) => {
    input.current.value = "";
    if (files.length && show) await ask("picture", () => uploadSlideshowPictures(show.name, files));
  };
  const off = !!busy || !!media.error;
  return (
    <>
      <select data-testid="stream-square-slideshow" value={card.slideshow || ""} onChange={(e) => (setCard({ slideshow: e.target.value || null, image: null }), setRemoving(null))} style={box()}>
        <option value="">{media.slideshows.length ? "Choose a slideshow…" : "No slideshows yet"}</option>
        {card.slideshow && !show && <option value={card.slideshow}>{card.slideshow} (not in the folder)</option>}
        {media.slideshows.map((x) => <option key={x.name} value={x.name}>{x.name} ({x.images.length})</option>)}
      </select>
      <input ref={input} data-testid="stream-slideshow-file" type="file" multiple accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => addPictures([...e.target.files])} />
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" data-testid="stream-slideshow-new" onClick={() => (setName(""), setRemoving(null))} disabled={off} style={headerButton()}>
          New slideshow
        </button>
        <button
          type="button" data-testid="stream-slideshow-add" onClick={() => input.current.click()} disabled={off || !show} style={headerButton()}
          title={show ? `Add pictures to “${show.name}”` : "Choose a slideshow first"}
        >
          Add pictures
        </button>
        <button
          type="button" data-testid="stream-slideshow-open-folder" onClick={() => setOpening(!opening)} style={{ ...headerButton(), color: opening ? c.amber : c.textMuted }}
          title="Where the slideshow's folder is, to open it in File Explorer"
        >
          Open folder
        </button>
        <button type="button" data-testid="stream-slideshow-delete" onClick={() => setRemoving("show")} disabled={off || !show} style={headerButton()}>
          Delete slideshow
        </button>
        {busy === "picture" && <span style={uiText(12, c.textFaint)}>Working…</span>}
      </div>
      {opening && <OpenFolder media={media} show={show} />}
      {name !== null && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <input
            data-testid="stream-slideshow-name" autoFocus value={name} maxLength={100} placeholder="The new slideshow's name" onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => (e.key === "Enter" ? create() : e.key === "Escape" && setName(null))} style={{ ...box(), width: 200 }}
          />
          <button type="button" data-testid="stream-slideshow-create" onClick={create} disabled={off || !name.trim()} style={headerButton()}>
            Make it
          </button>
          <button type="button" onClick={() => setName(null)} style={headerButton()}>
            Cancel
          </button>
        </div>
      )}
      {removing === "show" && show && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <span style={uiText(12, c.textMuted)}>Delete the slideshow “{show.name}” and its {show.images.length} pictures?</span>
          <button type="button" onClick={() => ask("picture", () => removeSlideshow(show.name)).then(() => setRemoving(null))} style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}>
            Delete
          </button>
          <button type="button" onClick={() => setRemoving(null)} style={headerButton()}>
            Keep
          </button>
        </div>
      )}
      <label style={label12}>
        Show each picture for
        <input
          data-testid="stream-slideshow-seconds" type="number" min={3} max={3600} value={card.seconds}
          onChange={(e) => setCard({ seconds: e.target.value === "" ? "" : Number(e.target.value) })} style={{ ...box(), width: 80 }}
        />
        seconds <span style={uiText(11, c.textFaint)}>(3 to 3600)</span>
      </label>
      {show && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {show.images.length === 0 && <span style={uiText(12, c.textFaint)}>No pictures in it yet: Add pictures or Open folder.</span>}
          {show.images.map((n) => (
            <div key={n} style={{ width: 96, display: "flex", flexDirection: "column", gap: 3 }}>
              <div style={{ height: 54, background: fixed.camera, borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center" }} title={n}>
                <img src={slideshowPictureUrl(show.name, n)} alt={n} style={{ maxWidth: "90%", maxHeight: "90%", objectFit: "contain" }} />
              </div>
              {removing === n ? (
                <div style={{ display: "flex", gap: 3 }}>
                  <button type="button" onClick={() => ask("picture", () => removeSlideshowPicture(show.name, n)).then(() => setRemoving(null))} style={{ ...headerButton(), color: c.danger, borderColor: c.danger, padding: "0 5px" }}>
                    Delete
                  </button>
                  <button type="button" onClick={() => setRemoving(null)} style={{ ...headerButton(), padding: "0 5px" }}>
                    Keep
                  </button>
                </div>
              ) : (
                <button type="button" onClick={() => setRemoving(n)} title={n} style={{ ...headerButton(), justifyContent: "center", padding: "0 5px" }}>
                  Delete
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <div style={help}>
        Each slideshow is a folder in the stream folder's slideshows folder: its pictures show one after another, in name order, round
        and round. Pictures copied into it yourself count too. One slideshow can be in several squares.
      </div>
    </>
  );
}

// Where a slideshow's folder is (or the slideshows folder, with none chosen), to open in File Explorer: a web page can't
// open a window on this computer itself, so it's shown as Windows reaches it over the network (\\server\share\...) to
// copy and paste into File Explorer's address bar. A stream folder that isn't on a network share can't be reached so.
function OpenFolder({ media, show }) {
  const field = useRef(null);
  const [copied, setCopied] = useState(false);
  const rest = show ? `slideshows\\${show.name}` : "slideshows";
  const where = media.windows_path ? `${media.windows_path}\\${rest}` : null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(where); // only on https or this computer's own address
    } catch {
      field.current.select(); // elsewhere, the browser's own copy of what's selected
      document.execCommand("copy");
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  if (!where) {
    return (
      <div style={uiText(12, c.textMuted, { lineHeight: 1.5 })}>
        The stream folder is in Farmhand's own storage (<span style={{ ...ui, fontFamily: "monospace" }}>{media.path}</span>), not on a network share, so
        Windows can't open it. Choose a stream folder on your NAS in Settings to open it from here.
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          ref={field} data-testid="stream-slideshow-path" readOnly value={where} onFocus={(e) => e.target.select()}
          style={{ ...box(), flex: 1, minWidth: 0, fontFamily: "monospace" }}
        />
        <button type="button" data-testid="stream-slideshow-copy-path" onClick={copy} style={headerButton()}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div style={uiText(11, c.textFaint, { lineHeight: 1.5 })}>
        Paste it into File Explorer's address bar (a web page can't open File Explorer itself). Pictures you put in it show up here.
      </div>
    </div>
  );
}

// What a card looks like, in the preview and on the editor's canvas, as the stream draws it: its colour, its picture
// (or slideshow, on this page's own clock) fitted into its box, and its words over that, centred on their spot and sized
// to the square. `edit`: on the editor's canvas, and on the preview's square being edited, where the picture and the words are dragged to move them and by their corner
// handle to resize them, `onChange({ picture_box } | { text_box })` taking each step ("quiet": on the preview, where the
// outline and corner only show while the picture or words are pointed at).
export function CardScreen({ card, media, streamBackground, edit = false, onChange }) {
  const [el, setEl] = useState(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [shot, setShot] = useState(0);
  const [natural, setNatural] = useState(null); // the picture's own width over height, once loaded
  const drag = useRef(null); // { what: "picture" | "pictureSize" | "text" | "textSize", x, y (where it started), from (the box then) }
  useEffect(() => {
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  const show = card.slideshow ? media.slideshows.find((x) => x.name === card.slideshow) : null;
  const count = show?.images.length || 0;
  useEffect(() => {
    setShot(0);
    if (count < 2) return;
    const timer = setInterval(() => setShot((s) => (s + 1) % count), Math.max(1, Number(card.seconds) || 10) * 1000);
    return () => clearInterval(timer);
  }, [card.slideshow, count, card.seconds]);
  const src = show && count ? slideshowPictureUrl(show.name, show.images[shot % count]) : card.image && media.images.includes(card.image) ? streamPictureUrl(card.image) : null;
  const pb = card.picture_box || FULL_BOX;
  // where the picture itself is: fitted into its box keeping its shape (as the stream fits it), so its outline and
  // corner handle sit on the picture, not on the box round it
  const shown = (() => {
    if (!natural || !size.w || !size.h) return pb;
    const bw = pb.w * size.w, bh = pb.h * size.h;
    const [w, h] = bw / bh > natural ? [bh * natural, bh] : [bw, bw / natural];
    return { x: pb.x + (bw - w) / 2 / size.w, y: pb.y + (bh - h) / 2 / size.h, w: w / size.w, h: h / size.h };
  })();
  const tb = card.text_box || MIDDLE;
  const words = card.text?.trim();
  const px = Math.max(6, size.h * tb.size);

  const start = (what) => (e) => {
    if (!edit) return;
    e.preventDefault();
    e.stopPropagation();
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur(); // the text box typed in lets go
    window.getSelection()?.removeAllRanges();
    dragged.current = false;
    drag.current = { what, x: e.clientX, y: e.clientY, from: what.startsWith("picture") ? shown : tb }; // the box closes round the picture
    el.setPointerCapture(e.pointerId);
  };
  const move = (e) => {
    const d = drag.current;
    if (!d || !size.w || !size.h) return;
    const dx = (e.clientX - d.x) / size.w;
    const dy = (e.clientY - d.y) / size.h;
    const f = d.from;
    if (d.what === "picture") onChange({ picture_box: { ...f, x: clamp(f.x + dx, 0, 1 - f.w), y: clamp(f.y + dy, 0, 1 - f.h) } });
    else if (d.what === "text") onChange({ text_box: { ...f, x: clamp(f.x + dx, 0, 1), y: clamp(f.y + dy, 0, 1) } });
    else if (d.what === "textSize") onChange({ text_box: { ...f, size: clamp(f.size + dy, 0.02, 0.6) } });
    else {
      // the box keeps the picture's own shape, so its corner stays on the picture's
      let w = clamp(f.w + dx, 0.05, 1 - f.x);
      let h = natural ? (w * size.w) / natural / size.h : clamp(f.h + dy, 0.05, 1 - f.y);
      if (h > 1 - f.y) {
        h = 1 - f.y;
        if (natural) w = (h * size.h * natural) / size.w;
      }
      onChange({ picture_box: { ...f, w: clamp(w, 0.05, 1 - f.x), h: clamp(h, 0.05, 1 - f.y) } });
    }
  };
  const dragged = useRef(false); // a move just ended: the click that ends it isn't a click on the square
  const end = () => {
    if (drag.current) dragged.current = true;
    drag.current = null;
  };
  const swallowClick = (e) => {
    if (!dragged.current) return;
    dragged.current = false;
    e.stopPropagation();
  };
  // the outline and corner: always on the editor's canvas; on the preview's square only while pointed at or moved
  const [hover, setHover] = useState(null); // "picture" | "text" under the pointer
  const marked = (what) => edit && (edit !== "quiet" || hover === what || drag.current?.what.startsWith(what));
  const outlineOf = (what) => (edit ? { cursor: "move", ...(marked(what) ? { outline: `1px dashed ${c.amber}` } : {}) } : {});
  // the corner to drag: inside the picture's own corner (so a picture filling the square still has one to grab), out
  // from the words'
  const handle = (what, title) =>
    marked(what === "pictureSize" ? "picture" : "text") && (
      <div
        data-testid={`stream-canvas-${what}`} title={title} onPointerDown={start(what)}
        style={{ position: "absolute", right: what === "pictureSize" ? 0 : -7, bottom: what === "pictureSize" ? 0 : -7, width: 14, height: 14, background: c.amber, border: `1px solid ${fixed.cameraText}`, cursor: "nwse-resize", pointerEvents: "auto" }}
      />
    );

  return (
    <div
      ref={setEl} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onClickCapture={swallowClick}
      style={{
        position: "relative", width: "100%", height: "100%", background: card.background || streamBackground, overflow: "hidden",
        touchAction: edit ? "none" : undefined, userSelect: edit ? "none" : undefined,
      }}
    >
      {src && (
        <div
          data-testid="stream-canvas-picture" onPointerDown={start("picture")} onClick={edit ? (e) => e.stopPropagation() : undefined}
          onPointerEnter={() => setHover("picture")} onPointerLeave={() => setHover(null)}
          style={{ position: "absolute", left: `${shown.x * 100}%`, top: `${shown.y * 100}%`, width: `${shown.w * 100}%`, height: `${shown.h * 100}%`, pointerEvents: edit ? "auto" : "none", ...outlineOf("picture") }}
        >
          <img
            src={src} alt="" draggable={false} onLoad={(e) => e.target.naturalHeight && setNatural(e.target.naturalWidth / e.target.naturalHeight)}
            style={{ width: "100%", height: "100%", objectFit: "contain", display: "block", pointerEvents: "none" }}
          />
          {handle("pictureSize", "Drag to make the picture bigger or smaller")}
        </div>
      )}
      {(card.slideshow && !count) || (card.image && !src) ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", ...ui, fontSize: fs(11), color: fixed.cameraMessage, pointerEvents: "none" }}>
          {card.slideshow ? "No pictures in the slideshow yet" : "Picture not in the stream folder"}
        </div>
      ) : null}
      {words && (
        <div
          data-testid="stream-canvas-text" onPointerDown={start("text")} onPointerEnter={() => setHover("text")} onPointerLeave={() => setHover(null)} onClick={edit ? (e) => e.stopPropagation() : undefined}
          style={{
            position: "absolute", left: `${tb.x * 100}%`, top: `${tb.y * 100}%`, transform: "translate(-50%, -50%)", pointerEvents: edit ? "auto" : "none",
            color: card.color, fontFamily: fontFamily(card.font), fontSize: px, lineHeight: 1.25, textAlign: "center", whiteSpace: "pre",
            background: card.band ? fixed.cameraBadge : "transparent", padding: card.band ? `0 ${px / 5}px` : 0, ...outlineOf("text"),
          }}
        >
          {words}
          {handle("textSize", "Drag down to make the words bigger, up to make them smaller")}
        </div>
      )}
    </div>
  );
}
