import { useEffect, useState } from "react";
import { c, fixed } from "../theme.js";
import { headerButton, panelBox, primaryButton, uiText } from "../styles.js";
import { colourBox, help, label12 } from "./streamStyles.js";
import { CardScreen } from "./CardScreen.jsx";
import { CARD, layersOf } from "./shapes.js";
import { LayersChoice } from "./LayersChoice.jsx";
import { CameraChoice, CameraWordsChoice, TextChoice } from "./SquareChoices.jsx";
import { PictureChoice, SlideshowChoice } from "./MediaChoices.jsx";

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
// page now, whether anything isn't saved yet; `slide`: the slideshow gone through by hand (StreamPreview's); `onDone`
// closes the editor.

const KINDS = [["camera", "Camera"], ["text", "Text"], ["picture", "Picture"], ["slideshow", "Slideshow"], ["empty", "Empty"]];
const isCardKind = (k) => ["text", "picture", "slideshow"].includes(k);
export const kindOf = (cell) => (!cell ? "empty" : cell.camera ? "camera" : cell.slideshow ? "slideshow" : cell.image ? "picture" : "text");
export function SquareEditor({ cells, i, onCells, cameras, media, fonts = [], streamText = {}, inset = 0, slide = null, showStatus = true, label, screen, aspect = 16 / 9, onDone, onSave, dirty, saving, ask, busy, streamBackground, onRenameSlideshow }) {
  const cell = cells[i];
  const [kind, setKind] = useState(kindOf(cell));
  useEffect(() => setKind(kindOf(cells[i])), [i]); // another square clicked
  const [layer, setLayer] = useState(null); // the extra picture or words chosen (its place in the list)
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
  // the slideshow picture on show (in the preview's square and on the canvas alike): words written now go with it
  const showNow = kind === "slideshow" && card.slideshow ? media.slideshows.find((x) => x.name === card.slideshow) : null;
  const slideName = showNow?.images.length ? showNow.images[(slide?.at || 0) % showNow.images.length] : null;
  useEffect(() => setLayer(null), [i, slideName, kind]); // another square, screen or kind: none chosen
  // more pictures and words: on any card (a slideshow's, on the screen on show)
  const layered = isCardKind(kind) && layersOf(card, slideName) !== null;
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
            {isCard ? <CardScreen card={card} media={media} streamBackground={streamBackground} streamText={streamText} inset={inset} edit onChange={setCard} slide={kind === "slideshow" ? slide : null} layer={layer} onLayer={setLayer} /> : screen}
          </div>
          {isCard && (card.text.trim() || card.image || card.slideshow) && (
            <div style={uiText(11, c.textFaint)}>Drag the {card.image || card.slideshow ? "picture or words" : "words"} to move them; drag a corner to make them bigger or smaller.</div>
          )}
          {layered && (
            <LayersChoice
              card={card} setCard={setCard} media={media} slideName={slideName} fonts={fonts} streamText={streamText} ask={ask} busy={busy}
              layer={layer} setLayer={setLayer}
            />
          )}
        </div>
        <div style={{ flex: "1 1 280px", minWidth: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {kind === "camera" && <CameraChoice cells={cells} i={i} onCells={onCells} cameras={cameras} label={label} />}
          {kind === "picture" && <PictureChoice card={card} setCard={setCard} media={media} ask={ask} busy={busy} />}
          {kind === "slideshow" && <SlideshowChoice card={card} setCard={setCard} media={media} ask={ask} busy={busy} slide={slide} onRename={onRenameSlideshow} />}
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
          {isCard && <TextChoice card={card} setCard={setCard} fonts={fonts} streamText={streamText} slideName={slideName} />}
          {kind === "camera" && cell?.camera && <CameraWordsChoice cell={cell} put={put} fonts={fonts} showStatus={showStatus} streamText={streamText} />}
          {kind === "empty" && <div style={help}>Shows the stream's background colour. Choose what the square shows above.</div>}
          {media.error && kind !== "camera" && kind !== "empty" && <div style={uiText(12, c.amber, { lineHeight: 1.5 })}>The stream folder isn't available: {media.error}</div>}
        </div>
      </div>
    </div>
  );
}
