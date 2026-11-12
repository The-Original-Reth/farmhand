import { useState } from "react";
import { fixed, fs, ui } from "../theme.js";
import { CameraPicture } from "../monitor/players.jsx";
import { CardScreen } from "./CardScreen.jsx";
import { fontFamily, statusLine } from "./shapes.js";

// One square of the preview, and the square editor's own copy of it.

// What a square shows: a camera, or a card (its colour, picture or slideshow, and words); nothing (the stream's colour)
// when null
export function Screen({ sq, showStatus, big, media, back, words = {}, clock = null, inset = 0, edit = false, onChange, slide = null, still = false }) {
  if (!sq) return null;
  if (sq.type === "camera") {
    return (
      <div style={{ position: "relative", width: "100%", height: "100%", background: sq.background || back, display: "flex", containerType: "size" }}>
        <CameraSquare sq={sq} showStatus={showStatus} big={big} words={words} inset={inset} />
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
  // (the plugin gives each picture already turned the way Mainsail shows the camera, as the stream does: not turned here)
  const fill = { width: "100%", height: "100%", objectFit: "contain", display: "block", border: 0, pointerEvents: "none" };
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
      {showStatus && own.show_words !== false && (
        <div
          data-testid="stream-preview-words"
          style={{
            position: "absolute", left: "1.5cqh", bottom: "2cqh", maxWidth: "calc(100% - 3cqh)", padding: "0.3em 0.5em", background: fixed.cameraBadge,
            color: own.words_color || words.color || fixed.cameraText, fontFamily: fontFamily(own.words_font || words.font),
            // as the stream sizes them: their own part of the square's height, else to fit (a 18th of its height, at most a 32nd of its width)
            fontSize: own.words_size ? `${own.words_size * 100}cqh` : big ? `${100 / 26}cqh` : `max(10px, min(${100 / 18}cqh, ${100 / 32}cqw))`,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", pointerEvents: "none",
          }}
        >
          {statusLine(label, sq.print)}
        </div>
      )}
    </>
  );
}
