// The Stream page's squares as the server keeps them (services/live_stream/squares.py), shared by the Stream page's
// routes (routes/stream.js) and the saved layouts in the settings (routes/settings.js): a camera with only what differs
// from the usual, or a card with every part filled in. These never refuse anything; routes/stream.js checks first.

// the fonts a square's words can be written in (a few of the server's; the mockup has no font files, so the page falls back)
export const FONTS = [
  ["dejavu-sans", "DejaVu Sans", "sans-serif"], ["play", "Play (Farmhand's own)", "sans-serif"], ["dejavu-sans-bold", "DejaVu Sans Bold", "sans-serif"],
  ["dejavu-serif", "DejaVu Serif", "serif"], ["dejavu-mono", "DejaVu Sans Mono", "monospace"], ["liberation-sans", "Liberation Sans (like Arial)", "sans-serif"],
  ["roboto-black", "Roboto Black", "sans-serif"], ["bebas-neue", "Bebas Neue (capitals)", "sans-serif"], ["comic-neue", "Comic Neue", "cursive"],
];
export const DEFAULT_FONT = "play";
export const CARD = {
  background: null, image: null, slideshow: null, seconds: 10, text: "", color: null, font: null, band: false,
  picture_box: { x: 0, y: 0, w: 1, h: 1 }, text_box: { x: 0.5, y: 0.5, size: 0.125 }, captions: {}, picture_boxes: {},
  layers: [], slide_layers: {},
};
const MAX_LAYERS = 12;

export const hex = (v, d) => (/^#[0-9A-Fa-f]{6}$/.test(v || "") ? v.toUpperCase() : d);
export const fileName = (v) => (typeof v === "string" && /^[^/\\]{1,120}$/.test(v) && v !== "." && v !== ".." ? v : null);
const part = (v, least, most, d) => (typeof v === "number" && Number.isFinite(v) ? Math.round(Math.min(most, Math.max(least, v)) * 1e4) / 1e4 : d);

// where a card's picture and words are, as parts of the square (0 to 1), kept inside it; cards of before had a size and
// a place for their words instead
const pictureBox = (b) => {
  if (!b || typeof b !== "object") return { ...CARD.picture_box };
  const w = part(b.w, 0.05, 1, 1), h = part(b.h, 0.05, 1, 1);
  return { x: part(b.x, 0, 1 - w, (1 - w) / 2), y: part(b.y, 0, 1 - h, (1 - h) / 2), w, h };
};
const textBox = (b, size, position) =>
  b && typeof b === "object"
    ? { x: part(b.x, 0, 1, 0.5), y: part(b.y, 0, 1, 0.5), size: part(b.size, 0.02, 0.6, 0.125) }
    : { x: 0.5, y: { top: 0.18, bottom: 0.82 }[position] ?? 0.5, size: Math.round(({ small: 1 / 12, large: 1 / 5 }[size] ?? 0.125) * 1e4) / 1e4 };

// more pictures and words on a card, each placed on its own (a slideshow's: each screen's own, by its picture's name):
// { type: "picture", image, box: { x, y, w, h } } | { type: "text", text, box: { x, y, size }, font, color, band }
const layersOf = (list) =>
  (Array.isArray(list) ? list : []).slice(0, MAX_LAYERS).flatMap((l) => {
    if (l?.type === "picture") return [{ type: "picture", image: fileName(l.image), box: pictureBox(l.box) }];
    if (l?.type === "text" && typeof l.text === "string") {
      return [{ type: "text", text: l.text.slice(0, 500), box: textBox(l.box), font: FONTS.some(([k]) => k === l.font) ? l.font : null, color: hex(l.color, null), band: l.band === true }];
    }
    return [];
  });

// a camera's square, and only what differs from the usual: its colour round it, and its words (shown, size, colour, font)
export const cameraCell = (x) => {
  const out = { camera: x.camera };
  if (hex(x.background, null)) out.background = hex(x.background, null);
  if (x.show_words === false) out.show_words = false;
  if (typeof x.words_size === "number" && Number.isFinite(x.words_size)) out.words_size = part(x.words_size, 0.02, 0.3, 0.06);
  if (hex(x.words_color, null)) out.words_color = hex(x.words_color, null);
  if (FONTS.some(([k]) => k === x.words_font)) out.words_font = x.words_font;
  return out;
};

// whether something sent is a card (it says what's on it)
export const isCard = (x) => !!x && typeof x === "object" && ["background", "image", "slideshow", "text"].some((k) => k in x);

// a card with every part filled in; its words trimmed to 500 characters
export const cardCell = (x) => ({
  ...CARD,
  background: hex(x.background, null), image: x.slideshow ? null : fileName(x.image), slideshow: fileName(x.slideshow),
  seconds: Number.isInteger(x.seconds) && x.seconds >= 3 && x.seconds <= 3600 ? x.seconds : 10,
  text: typeof x.text === "string" ? x.text.trim().slice(0, 500) : "", color: hex(x.color, null), // null: the stream's
  font: FONTS.some(([k]) => k === x.font) ? x.font : null, band: x.band === true,
  picture_box: pictureBox(x.picture_box), text_box: textBox(x.text_box, x.size, x.position),
  // a slideshow's pictures' own size and place, each resized or moved on its own
  picture_boxes: x.slideshow && x.picture_boxes && typeof x.picture_boxes === "object"
    ? Object.fromEntries(Object.entries(x.picture_boxes).filter(([name, b]) => fileName(name) && b && typeof b === "object").map(([name, b]) => [name, pictureBox(b)]))
    : {},
  // more pictures and words: a Text or Picture square's, and each screen's of a slideshow
  layers: !x.slideshow ? layersOf(x.layers) : [],
  slide_layers: x.slideshow && x.slide_layers && typeof x.slide_layers === "object"
    ? Object.fromEntries(Object.entries(x.slide_layers).filter(([name]) => fileName(name)).map(([name, list]) => [name, layersOf(list)]).filter(([, list]) => list.length))
    : {},
  // a slideshow's pictures' own words, kept with the picture they were written on
  captions: x.slideshow && x.captions && typeof x.captions === "object"
    ? Object.fromEntries(Object.entries(x.captions)
      .filter(([name, cap]) => fileName(name) && cap && typeof cap.text === "string" && cap.text.trim())
      .map(([name, cap]) => [name, { text: cap.text.trim().slice(0, 500), text_box: textBox(cap.text_box) }]))
    : {},
});
