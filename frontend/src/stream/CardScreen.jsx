import { useEffect, useRef, useState } from "react";
import { c, fixed, fs, ui } from "../theme.js";
import { slideshowPictureUrl, streamFontUrl, streamPictureUrl } from "../api.js";
import { FULL_BOX, MIDDLE, fontFamily, isBlank } from "./shapes.js";

// What a card looks like (CardScreen), in the preview and on the editor's canvas, and the stream's fonts: what a
// card is made of (CARD), and each font loaded from the server so the words look here as on the stream.

// The stream's fonts, loaded from the server so the words look here as they do on the stream: `fonts` [{ key, generic }]
export function StreamFonts({ fonts }) {
  const css = fonts.map((f) => `@font-face { font-family: "fh-stream-${f.key}"; src: url("${streamFontUrl(f.key)}"); font-display: swap; }`).join("\n");
  return <style>{css}</style>;
}
const clamp = (v, least, most) => Math.round(Math.min(most, Math.max(least, v)) * 1e4) / 1e4;
// What a card looks like, in the preview and on the editor's canvas, as the stream draws it: its colour, its picture
// (or slideshow, on this page's own clock) fitted into its box, and its words over that, centred on their spot and sized
// to the square. `edit`: on the editor's canvas, and on the preview's square being edited, where the picture and the words are dragged to move them and by their corner
// handle to resize them, `onChange({ picture_box } | { picture_boxes } | { text_box })` taking each step (a slideshow's
// picture is resized or moved on its own, in picture_boxes by its name) ("quiet": on the preview, where the
// outline and corner only show while the picture or words are pointed at). `streamText`: { font, color }, the stream's
// words', for a card that has none of its own. `slide`: { at (which picture) }, a slideshow gone through by
// hand (StreamPreview keeps it, so the preview's square and the canvas show the same picture); without it the slideshow
// plays on its own, or, with `clock` (seconds the stream has run, while live), shows the picture the stream shows now.
// A slideshow picture with words of its own (card.captions) shows those instead of the card's.
// `inset`: the square's border, as a part of its height: the picture is fitted inside it, as the stream fits it.
export function CardScreen({ card, media, streamBackground, streamText = {}, inset = 0, edit = false, onChange, slide = null, clock = null }) {
  const [el, setEl] = useState(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [ownShot, setOwnShot] = useState(0);
  // `slide`: { at, playing, go(at) } when the editor goes through a slideshow by hand; else it plays on its own
  // the picture on show: gone through by hand (slide), on the stream's own time (clock, while live), or its own
  const sec = Math.max(1, Number(card.seconds) || 10);
  const showCount = card.slideshow ? media.slideshows.find((x) => x.name === card.slideshow)?.images.length || 0 : 0;
  const shot = slide ? slide.at : clock !== null && showCount ? Math.floor((clock % (showCount * sec)) / sec) : ownShot;
  const setShot = slide ? (f) => slide.go(f(slide.at)) : setOwnShot;
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
    if (!slide) setOwnShot(0);
    if (slide || clock !== null || count < 2) return; // gone through by hand or on the stream's time, or nothing to go round
    const timer = setInterval(() => setShot((s) => (s + 1) % count), Math.max(1, Number(card.seconds) || 10) * 1000);
    return () => clearInterval(timer);
  }, [card.slideshow, count, card.seconds, !!slide, clock !== null]);
  const src = show && count ? (isBlank(show.images[shot % count]) ? null : slideshowPictureUrl(show.name, show.images[shot % count])) : card.image && media.images.includes(card.image) ? streamPictureUrl(card.image) : null;
  // a slideshow's picture on show: its own size and place when it has been resized or moved on its own, else the card's
  const onShow = show && count && !isBlank(show.images[shot % count]) ? show.images[shot % count] : null;
  const pb = (onShow && card.picture_boxes?.[onShow]) || card.picture_box || FULL_BOX;
  const setPictureBox = (b) => (card.slideshow && onShow ? onChange({ picture_boxes: { ...card.picture_boxes, [onShow]: b } }) : onChange({ picture_box: b }));
  // the part of the square inside its border, in px: a picture's box is a part of it (so the border never covers it)
  const edge = inset * size.h;
  const iw = Math.max(1, size.w - 2 * edge), ih = Math.max(1, size.h - 2 * edge);
  // where the picture itself is: fitted into its box keeping its shape (as the stream fits it), so its outline and
  // corner handle sit on the picture, not on the box round it
  const shown = (() => {
    if (!natural || !size.w || !size.h) return pb;
    const bw = pb.w * iw, bh = pb.h * ih;
    const [w, h] = bw / bh > natural ? [bh * natural, bh] : [bw, bw / natural];
    return { x: pb.x + (bw - w) / 2 / iw, y: pb.y + (bh - h) / 2 / ih, w: w / iw, h: h / ih };
  })();
  // ... and on the square, as parts of its width and height
  const at = size.w && size.h
    ? { x: (edge + shown.x * iw) / size.w, y: (edge + shown.y * ih) / size.h, w: (shown.w * iw) / size.w, h: (shown.h * ih) / size.h }
    : shown;
  // a slideshow picture's own words (kept with it), else the card's own
  const name = show && count ? show.images[shot % count] : null;
  const cap = name ? card.captions?.[name] : null;
  const tb = (cap ? cap.text_box : card.text_box) || MIDDLE;
  const words = (cap ? cap.text : card.text)?.trim();
  const setTextBox = (b) => (cap ? onChange({ captions: { ...card.captions, [name]: { ...cap, text_box: b } } }) : onChange({ text_box: b }));
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
    const px_ = (e.clientX - d.x) / iw; // the picture moves within the part inside the border
    const py_ = (e.clientY - d.y) / ih;
    const f = d.from;
    if (d.what === "picture") setPictureBox({ ...f, x: clamp(f.x + px_, 0, 1 - f.w), y: clamp(f.y + py_, 0, 1 - f.h) });
    else if (d.what === "text") setTextBox({ ...f, x: clamp(f.x + dx, 0, 1), y: clamp(f.y + dy, 0, 1) });
    else if (d.what === "textSize") setTextBox({ ...f, size: clamp(f.size + dy, 0.02, 0.6) });
    else {
      // the box keeps the picture's own shape, so its corner stays on the picture's
      let w = clamp(f.w + px_, 0.05, 1 - f.x);
      let h = natural ? (w * iw) / natural / ih : clamp(f.h + py_, 0.05, 1 - f.y);
      if (h > 1 - f.y) {
        h = 1 - f.y;
        if (natural) w = (h * ih * natural) / iw;
      }
      setPictureBox({ ...f, w: clamp(w, 0.05, 1 - f.x), h: clamp(h, 0.05, 1 - f.y) });
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
          style={{ position: "absolute", left: `${at.x * 100}%`, top: `${at.y * 100}%`, width: `${at.w * 100}%`, height: `${at.h * 100}%`, pointerEvents: edit ? "auto" : "none", ...outlineOf("picture") }}
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
            color: card.color || streamText.color || "#FFFFFF", fontFamily: fontFamily(card.font || streamText.font), fontSize: px, lineHeight: 1.25, textAlign: "center", whiteSpace: "pre",
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
