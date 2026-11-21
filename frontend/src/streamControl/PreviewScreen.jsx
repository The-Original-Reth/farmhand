import { useState } from "react";
import { c, fixed, fs, ui } from "../theme.js";
import { CameraPicture } from "../monitor/players.jsx";
import { CardScreen } from "./CardScreen.jsx";
import { cameraTextCard, fontFamily, statusLine } from "./shapes.js";

// One square of the preview, and the square editor's own copy of it.

// What a square shows: a camera, or a card (its colour, picture or slideshow, and words); nothing (the stream's colour)
// when null. `cameraText`: a camera's pieces of text drawn over it (not on the square editor's canvas, which draws its own)
export function Screen({ sq, showStatus, big, media, back, words = {}, clock = null, inset = 0, edit = false, onChange, slide = null, still = false, cameraText = true }) {
  if (!sq) return null;
  if (sq.type === "camera") {
    return (
      <div style={{ position: "relative", width: "100%", height: "100%", background: sq.background || back, display: "flex", containerType: "size" }}>
        <CameraSquare sq={sq} showStatus={showStatus} big={big} words={words} inset={inset} />
        {cameraText && sq.cell?.layers?.length > 0 && (
          <div data-testid="stream-preview-camera-text" style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
            <CardScreen card={cameraTextCard(sq.cell)} media={media} streamBackground="transparent" streamText={words} inset={inset} />
          </div>
        )}
      </div>
    );
  }
  if (sq.type === "card") return <CardScreen card={sq.cell} media={media} streamBackground={back} streamText={words} inset={inset} edit={edit} onChange={onChange} slide={slide || null} clock={clock} still={still} />;
  return null;
}

// `inset`: the square's border, as a part of its height: the camera is fitted inside it, as the stream fits it
function CameraSquare({ sq, showStatus, big, words = {}, inset = 0 }) {
  const [state, setState] = useState("waiting"); // waiting | showing | failed
  const { cam, label } = sq;
  const own = sq.cell || {}; // the square's own choices for its words (show_words, words_size, words_color, words_font)
  // Turned and flipped the way Mainsail is set to show the camera, as Monitor does and as the stream plugins turn it
  // (the camera's own picture comes untouched from Monitor's player)
  const turn = cam
    ? [cam.rotation ? `rotate(${cam.rotation}deg)` : "", cam.flip_horizontal ? "scaleX(-1)" : "", cam.flip_vertical ? "scaleY(-1)" : ""].join(" ").trim()
    : "";
  const fill = { width: "100%", height: "100%", objectFit: "contain", display: "block", border: 0, pointerEvents: "none", transform: turn || undefined };
  const message = !cam ? "Camera not found" : state === "failed" ? "Camera not answering" : state === "waiting" ? "Connecting…" : null;
  return (
    <>
      {cam && (
        <div style={{ position: "absolute", inset: `${inset * 100}cqh`, display: "flex" }}>
          <CameraPicture cam={cam} label={label} style={fill} onState={setState} />
        </div>
      )}
      {message && (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", ...ui, fontSize: fs(11), color: fixed.cameraMessage }}>
          {message}
        </div>
      )}
      {showStatus && own.show_words !== false && <CameraWords sq={sq} words={words} big={big} />}
    </>
  );
}

const PLACE_X = 0.95, PLACE_Y = 0.05; // as the backend keeps them: starting no further right, standing no higher
const clamp = (v, least, most) => Math.round(Math.min(most, Math.max(least, v)) * 1e4) / 1e4;

// A camera's printer name and print, on a band: low on the left, or where the square's words_place puts them (their
// left edge and their foot, as parts of the square's width and height). With `onPlace` they're dragged into place (the
// square editor), and onPlace({ x, y }) is told where. Inside a box with containerType "size" filling the square.
export function CameraWords({ sq, words = {}, big, onPlace = null }) {
  const own = sq.cell || {};
  const place = own.words_place;
  const [drag, setDrag] = useState(null); // { x, y (where the pointer started), from: { x, y }, w, h (the square, in px) }
  const start = (e) => {
    if (!onPlace) return;
    e.preventDefault();
    e.stopPropagation();
    const el = e.currentTarget;
    const box = el.parentElement.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    el.setPointerCapture(e.pointerId);
    setDrag({ x: e.clientX, y: e.clientY, w: box.width || 1, h: box.height || 1, from: { x: (r.left - box.left) / (box.width || 1), y: (r.bottom - box.top) / (box.height || 1) } });
  };
  const move = (e) => {
    if (!drag) return;
    onPlace({ x: clamp(drag.from.x + (e.clientX - drag.x) / drag.w, 0, PLACE_X), y: clamp(drag.from.y + (e.clientY - drag.y) / drag.h, PLACE_Y, 1) });
  };
  const end = () => setDrag(null);
  const where = place
    ? { left: `${place.x * 100}%`, top: `${place.y * 100}%`, transform: "translateY(-100%)", maxWidth: `calc(${(1 - place.x) * 100}% - 1.5cqh)` }
    : { left: "1.5cqh", bottom: "2cqh", maxWidth: "calc(100% - 3cqh)" };
  return (
    <div
      data-testid="stream-preview-words" title={onPlace ? "Drag to move the printer's name and print" : undefined}
      onPointerDown={start} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onClick={onPlace ? (e) => e.stopPropagation() : undefined}
      style={{
        position: "absolute", ...where, padding: "0.3em 0.5em", background: fixed.cameraBadge, boxSizing: "border-box",
        color: own.words_color || words.color || fixed.cameraText, fontFamily: fontFamily(own.words_font || words.font),
        // as the stream sizes them: their own part of the square's height, else to fit (a 18th of its height, at most a 32nd of its width)
        fontSize: own.words_size ? `${own.words_size * 100}cqh` : big ? `${100 / 26}cqh` : `max(10px, min(${100 / 18}cqh, ${100 / 32}cqw))`,
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        ...(onPlace ? { pointerEvents: "auto", cursor: "move", touchAction: "none", userSelect: "none", outline: `1px ${drag ? "solid" : "dashed"} ${c.amber}` } : { pointerEvents: "none" }),
      }}
    >
      {statusLine(sq.label, sq.print)}
    </div>
  );
}
