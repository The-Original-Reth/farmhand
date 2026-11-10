// What the Stream page's squares and cards are made of, and the server's own rules for them worked out the same way
// here (services/live_stream/), so the preview shows what the stream will. No React in here.

// ---- a card
export const FULL_BOX = { x: 0, y: 0, w: 1, h: 1 };
export const MIDDLE = { x: 0.5, y: 0.5, size: 0.125 };
export const CARD = { background: null, image: null, slideshow: null, seconds: 10, text: "", color: null, font: null, band: false, picture_box: FULL_BOX, text_box: MIDDLE, captions: {}, picture_boxes: {}, layers: [], slide_layers: {} };
// More pictures and words on a card, each placed on its own over what it shows: { type: "picture", image: a picture's
// file name, box: { x, y, w, h } } | { type: "text", text, box: { x, y, size }, font, color, band }. A Text or Picture
// square's are card.layers; a slideshow's are each screen's own, card.slide_layers[the picture's name, or "blank:N"].
export const MAX_LAYERS = 12;
export const newPicture = (image) => ({ type: "picture", image, box: { x: 0.3, y: 0.25, w: 0.4, h: 0.5 } });
export const newText = () => ({ type: "text", text: "New text", box: { x: 0.5, y: 0.5, size: 0.1 }, font: null, color: null, band: false });
// the extra pictures and words on what a card shows now (`slideName`: the slideshow's screen on show), and how to change them
export const layersOf = (card, slideName) =>
  card.slideshow ? (slideName ? card.slide_layers?.[slideName] || [] : null) : card.layers || [];
export const layersChange = (card, slideName, next) =>
  card.slideshow ? { slide_layers: { ...card.slide_layers, [slideName]: next } } : { layers: next };
// a slideshow's blank screen ("blank:2": Farmhand's own, no picture, just the square's colour and its words), and the
// name a slide is shown by
export const isBlank = (name) => typeof name === "string" && name.startsWith("blank:");
export const slideLabel = (name) => (isBlank(name) ? `Blank screen ${name.slice(6)}` : name);
// the page's own name for one of the stream's fonts (StreamFonts loads each from the server)
export const fontFamily = (key) => `"fh-stream-${key || "play"}", sans-serif`;

// ---- the grid
// the border round each square, in px of the 720-high picture (services/live_stream/constants.py BORDER_WIDTH)
export const BORDER_PX = 3;
export const MAX_SIDE = 5;

// The smallest near-square grid for n squares, as the server works it out (services/live_stream/choices.py auto_grid)
export const autoGrid = (n) => {
  const cols = Math.min(MAX_SIDE, Math.max(1, Math.ceil(Math.sqrt(n))));
  return { cols, rows: Math.min(MAX_SIDE, Math.max(1, Math.ceil(n / cols))) };
};

// The squares of a cols x rows grid made from those of another size: each stays where it was (row and column) when it
// still fits; ones that don't move into the first empty squares, and are left out when there are none.
export const resized = (cells, from, cols, rows) => {
  const out = Array(cols * rows).fill(null);
  const left = [];
  cells.forEach((cell, i) => {
    const r = Math.floor(i / from.cols);
    const col = i % from.cols;
    if (r < rows && col < cols) out[r * cols + col] = cell;
    else if (cell) left.push(cell);
  });
  for (let i = 0; i < out.length && left.length; i++) if (!out[i]) out[i] = left.shift();
  return out;
};

// The squares with a and b swapped
export const swapped = (cells, a, b) => {
  const next = [...cells];
  [next[a], next[b]] = [next[b], next[a]];
  return next;
};

// a camera's key, "printer id:camera name", taken apart
export const printerOf = (key) => Number(key.slice(0, key.indexOf(":")));
export const cameraOf = (key) => key.slice(key.indexOf(":") + 1);

// ---- what the stream shows, and when
// what's written under a camera, as the server writes it (services/live_stream/words.py status_line)
export const statusLine = (label, p) => {
  if (!p?.state) return p?.error ? `${label} · Status unknown` : `${label} · Idle`;
  let line = `${label} · ${p.state === "paused" ? "Paused" : "Printing"}`;
  if (typeof p.progress === "number") line += ` ${Math.round(p.progress)}%`;
  if (p.file) line += ` · ${String(p.file).split("/").pop().slice(0, 60)}`;
  return line;
};

// Which camera is on its own now, taking turns: its place among the cameras, or null while the whole grid is shown; and
// how long until the next turn. As the server works it out (services/live_stream/picture.py windows).
export const turnAt = (seconds, n, cycle) => {
  if (!cycle || n < 2) return { one: null, left: null };
  const period = cycle.all + n * cycle.each;
  const at = seconds % period;
  if (at < cycle.all) return { one: null, left: cycle.all - at };
  const one = Math.floor((at - cycle.all) / cycle.each);
  return { one, left: cycle.all + (one + 1) * cycle.each - at };
};
