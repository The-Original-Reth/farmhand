import { useEffect, useRef, useState } from "react";
import { c, fixed, fs, ui } from "../theme.js";
import { fieldBox, headerButton, panelBox, uiText } from "../styles.js";
import {
  createSlideshow, removeSlideshow, removeSlideshowPicture, removeStreamPicture, slideshowPictureUrl, streamPictureUrl, uploadSlideshowPictures,
  uploadStreamPictures,
} from "../api.js";

// The editor under the preview for the square clicked: the square on a screen of its own, and what it shows. Camera;
// Colour, Picture or Slideshow (a "card": the square's colour, a picture or a slideshow fitted over it, and words over
// that if you like); or Empty (the stream's background colour). Pictures are files in the stream folder (Settings):
// single ones in its images folder, each slideshow a folder in its slideshows folder. They're uploaded and deleted
// straight away (`ask`: the page's own way of asking the server); what the square holds is saved with the page's Save.
//
// `cells`, `i`: the grid's squares and the one being edited; `onCells(next)` changes them. `cameras`: [{ key, label }];
// `media`: { images, slideshows: [{ name, images }], error }; `label(key)`: a camera's name; `screen`: the square drawn as
// the preview draws it; `onDone` closes the editor.

const KINDS = [["camera", "Camera"], ["colour", "Colour"], ["picture", "Picture"], ["slideshow", "Slideshow"], ["empty", "Empty"]];
export const kindOf = (cell) => (!cell ? "empty" : cell.camera ? "camera" : cell.slideshow ? "slideshow" : cell.image ? "picture" : "colour");
export const CARD = { background: null, image: null, slideshow: null, seconds: 10, text: "", color: "#FFFFFF", size: "medium", position: "middle" };
const SIZES = [["small", "Small"], ["medium", "Medium"], ["large", "Large"]];
const PLACES = [["top", "Top"], ["middle", "Middle"], ["bottom", "Bottom"]];
const help = uiText(12, c.textFaint, { lineHeight: 1.5 });
const box = () => ({ ...fieldBox(), padding: "5px 8px" });
const label12 = uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6 });
const colourBox = { width: 30, height: 22, padding: 0, border: `1px solid ${c.border}`, background: "none", cursor: "pointer" };

export function SquareEditor({ cells, i, onCells, cameras, media, label, screen, onDone, ask, busy, streamBackground }) {
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
    else if (k === "colour") put({ ...card, image: null, slideshow: null, background: card.background || streamBackground });
    else if (k === "picture") put({ ...card, slideshow: null, image: card.image || media.images[0] || null });
    else put({ ...card, image: null, slideshow: card.slideshow || media.slideshows[0]?.name || null });
  };
  return (
    <div data-testid="stream-square-editor" style={panelBox({ padding: 12, marginTop: 10, display: "flex", gap: 14, flexWrap: "wrap" })}>
      <div style={{ width: 240, maxWidth: "100%", flexShrink: 0 }}>
        <div style={{ position: "relative", aspectRatio: "16 / 9", background: fixed.camera, border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden", display: "flex" }}>
          {screen}
        </div>
        <div style={uiText(11, c.textFaint, { marginTop: 4 })}>Square {i + 1}</div>
      </div>
      <div style={{ flex: 1, minWidth: 280, display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {KINDS.map(([k, name]) => (
            <button
              key={k} type="button" data-testid={`stream-square-kind-${k}`} onClick={() => choose(k)}
              style={{ ...headerButton(), color: kind === k ? c.amber : c.textMuted, borderColor: kind === k ? c.amber : c.border }}
            >
              {name}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <button type="button" onClick={onDone} style={headerButton()}>
            Done
          </button>
        </div>
        {kind === "camera" && <CameraChoice cells={cells} i={i} onCells={onCells} cameras={cameras} label={label} />}
        {kind === "picture" && <PictureChoice card={card} setCard={setCard} media={media} ask={ask} busy={busy} />}
        {kind === "slideshow" && <SlideshowChoice card={card} setCard={setCard} media={media} ask={ask} busy={busy} />}
        {["colour", "picture", "slideshow"].includes(kind) && (
          <>
            <label style={label12}>
              <input
                type="color" data-testid="stream-square-colour" value={(card.background || streamBackground).toLowerCase()}
                onChange={(e) => setCard({ background: e.target.value.toUpperCase() })} style={colourBox}
              />
              {kind === "colour" ? "The square's colour" : "Colour round the picture"}
              {card.background && (
                <button type="button" onClick={() => setCard({ background: null })} style={headerButton()} title="Use the stream's background colour">
                  Stream's colour
                </button>
              )}
            </label>
            <TextChoice card={card} setCard={setCard} />
          </>
        )}
        {kind === "empty" && <div style={help}>Shows the stream's background colour. Choose what the square shows above.</div>}
        {media.error && kind !== "camera" && kind !== "empty" && <div style={uiText(12, c.amber, { lineHeight: 1.5 })}>The stream folder isn't available: {media.error}</div>}
      </div>
    </div>
  );
}

// A camera: one in another square moves here
function CameraChoice({ cells, i, onCells, cameras, label }) {
  const cell = cells[i];
  const placed = new Set(cells.filter((x) => x?.camera).map((x) => x.camera));
  const pick = (key) => onCells(cells.map((x, j) => (j === i ? (key ? { camera: key } : null) : x?.camera === key ? null : x)));
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

// Words over the square, if you like
function TextChoice({ card, setCard }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: `1px solid ${c.border}`, paddingTop: 8 }}>
      <div style={uiText(12, c.textMuted)}>Text over it <span style={uiText(11, c.textFaint)}>(leave empty for none · {card.text.length}/500)</span></div>
      <textarea
        data-testid="stream-square-text" value={card.text} maxLength={500} rows={2} placeholder="Words to show over this square"
        onChange={(e) => setCard({ text: e.target.value })} style={{ ...box(), resize: "vertical", lineHeight: 1.4 }}
      />
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
        <label style={label12}>
          <input type="color" value={card.color.toLowerCase()} onChange={(e) => setCard({ color: e.target.value.toUpperCase() })} style={colourBox} />
          Text colour
        </label>
        <label style={label12}>
          Size
          <select data-testid="stream-square-text-size" value={card.size} onChange={(e) => setCard({ size: e.target.value })} style={box()}>
            {SIZES.map(([k, name]) => <option key={k} value={k}>{name}</option>)}
          </select>
        </label>
        <label style={label12}>
          Where
          <select data-testid="stream-square-text-position" value={card.position} onChange={(e) => setCard({ position: e.target.value })} style={box()}>
            {PLACES.map(([k, name]) => <option key={k} value={k}>{name}</option>)}
          </select>
        </label>
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

// One of the stream folder's slideshows (a folder of pictures shown in turn), or a new one; its pictures added or
// deleted; and how long each picture shows
function SlideshowChoice({ card, setCard, media, ask, busy }) {
  const input = useRef(null);
  const [name, setName] = useState("");
  const [removing, setRemoving] = useState(null); // "show" | a picture's name, asking "Delete?"
  const show = media.slideshows.find((x) => x.name === card.slideshow) || null;
  const create = async () => {
    const n = name.trim();
    if (!n) return;
    const p = await ask("picture", () => createSlideshow(n));
    if (p?.media.slideshows.some((x) => x.name === n)) {
      setCard({ slideshow: n, image: null });
      setName("");
    }
  };
  const addPictures = async (files) => {
    if (files.length) await ask("picture", () => uploadSlideshowPictures(show.name, files));
    input.current.value = "";
  };
  return (
    <>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <select data-testid="stream-square-slideshow" value={card.slideshow || ""} onChange={(e) => setCard({ slideshow: e.target.value || null, image: null })} style={box()}>
          <option value="">{media.slideshows.length ? "Choose a slideshow…" : "No slideshows yet"}</option>
          {card.slideshow && !show && <option value={card.slideshow}>{card.slideshow} (not in the folder)</option>}
          {media.slideshows.map((x) => <option key={x.name} value={x.name}>{x.name} ({x.images.length})</option>)}
        </select>
        <input
          data-testid="stream-slideshow-name" value={name} maxLength={100} placeholder="New slideshow's name" onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && create()} style={{ ...box(), width: 170 }}
        />
        <button type="button" data-testid="stream-slideshow-create" onClick={create} disabled={!!busy || !name.trim() || !!media.error} style={headerButton()}>
          New slideshow
        </button>
      </div>
      <label style={label12}>
        Show each picture for
        <input
          data-testid="stream-slideshow-seconds" type="number" min={3} max={3600} value={card.seconds}
          onChange={(e) => setCard({ seconds: e.target.value === "" ? "" : Number(e.target.value) })} style={{ ...box(), width: 80 }}
        />
        seconds <span style={uiText(11, c.textFaint)}>(3 to 3600)</span>
      </label>
      {show && (
        <>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
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
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input ref={input} data-testid="stream-slideshow-file" type="file" multiple accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => addPictures([...e.target.files])} />
            <button type="button" data-testid="stream-slideshow-add" onClick={() => input.current.click()} disabled={!!busy} style={headerButton()}>
              {busy === "picture" ? "Working…" : "Add pictures"}
            </button>
            {removing === "show" ? (
              <>
                <span style={uiText(12, c.textMuted)}>Delete the slideshow “{show.name}” and its {show.images.length} pictures?</span>
                <button type="button" onClick={() => ask("picture", () => removeSlideshow(show.name)).then(() => setRemoving(null))} style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}>
                  Delete
                </button>
                <button type="button" onClick={() => setRemoving(null)} style={headerButton()}>
                  Keep
                </button>
              </>
            ) : (
              <button type="button" onClick={() => setRemoving("show")} disabled={!!busy} style={headerButton()}>
                Delete slideshow
              </button>
            )}
          </div>
        </>
      )}
      <div style={help}>
        Each slideshow is a folder in the stream folder's slideshows folder: its pictures show one after another, in name order, round
        and round. Pictures copied into it yourself count too. One slideshow can be in several squares.
      </div>
    </>
  );
}

// What a card looks like, in the preview and on the editor's screen, as the stream draws it: its colour, its picture
// (or slideshow, on this page's own clock) fitted over it, and its words over that, sized to the square
export function CardScreen({ card, media, streamBackground }) {
  const [el, setEl] = useState(null);
  const [height, setHeight] = useState(0);
  const [shot, setShot] = useState(0);
  useEffect(() => {
    if (!el) return;
    const measure = () => setHeight(el.clientHeight);
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
  const ratio = { small: 1 / 12, medium: 1 / 8, large: 1 / 5 }[card.size] || 1 / 8;
  const size = Math.max(8, height * ratio);
  const place = { top: "flex-start", middle: "center", bottom: "flex-end" }[card.position] || "center";
  return (
    <div ref={setEl} style={{ position: "relative", width: "100%", height: "100%", background: card.background || streamBackground, overflow: "hidden" }}>
      {src && <img src={src} alt="" draggable={false} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", pointerEvents: "none" }} />}
      {(card.slideshow && !count) || (card.image && !src) ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", ...ui, fontSize: fs(11), color: fixed.cameraMessage }}>
          {card.slideshow ? "No pictures in the slideshow yet" : "Picture not in the stream folder"}
        </div>
      ) : null}
      {card.text?.trim() && (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: place, justifyContent: "center", padding: `${height / 14}px 4px`, pointerEvents: "none" }}>
          <span
            style={{
              color: card.color, ...ui, fontSize: size, lineHeight: 1.25, textAlign: "center", whiteSpace: "pre-wrap",
              background: src ? fixed.cameraBadge : "transparent", padding: src ? `0 ${size / 5}px` : 0,
            }}
          >
            {card.text.trim()}
          </span>
        </div>
      )}
    </div>
  );
}
