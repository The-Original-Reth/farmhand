import { c } from "../theme.js";

// ---- searching the Models list ----
// A search is split into words and EVERY word must be found ("great white" finds GreatWhiteShark; "frog shark"
// finds nothing). A word matches the model's own name first; failing that, the names of its 3MF files, the
// printers it's sliced for, or the slicer used. That makes "VT 1190" or "prusa" useful searches, and the row says
// which of those a model matched through, so a result is never a mystery.
export const searchWords = (query) => query.trim().toLowerCase().split(/\s+/).filter(Boolean);

// -> null if the model doesn't match every word; otherwise { reasons: [...] } (empty when its own name matched)
export function matchModel(model, words, others) {
  if (words.length === 0) return { reasons: [] };
  const name = model.name.toLowerCase();
  const reasons = [];
  for (const word of words) {
    if (name.includes(word)) continue;
    const hit = others.find((o) => o.text.toLowerCase().includes(word));
    if (!hit) return null;
    const reason = hit.kind === "note" ? `note “${excerptAround(hit.text, word)}”` : `${hit.kind} ${hit.text}`;
    if (!reasons.includes(reason)) reasons.push(reason);
  }
  return { reasons };
}

// A short stretch of a long text around where a word was found, for saying why something matched
function excerptAround(text, word) {
  const i = text.toLowerCase().indexOf(word);
  const start = Math.max(0, i - 24);
  const end = Math.min(text.length, i + word.length + 40);
  return (start > 0 ? "…" : "") + text.slice(start, end).replace(/\s+/g, " ").trim() + (end < text.length ? "…" : "");
}

// Everything besides its own name that a model can be found by
export function searchableExtras(model, bundles, printers) {
  const out = [];
  (model.versions || []).forEach((v) => v.filename && out.push({ kind: "file", text: v.filename }));
  bundles.forEach((b) => {
    const printer = printers.find((p) => p.id === b.printerId);
    if (printer) out.push({ kind: "printer", text: printer.name });
    (b.versions || []).forEach((v) => v.filename && out.push({ kind: "3MF", text: v.filename }));
    if (b.slicer) out.push({ kind: "slicer", text: b.slicer });
  });
  if (model.notes) out.push({ kind: "note", text: model.notes }); // last: a note only explains a match nothing else does
  return out;
}

// The text with the searched words picked out
export function Highlighted({ text, words }) {
  if (!words || words.length === 0) return text;
  const escaped = [...words].sort((a, b) => b.length - a.length).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const parts = text.split(new RegExp(`(${escaped.join("|")})`, "gi"));
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} data-testid="search-hit" style={{ background: c.amberDim, color: c.amber, borderRadius: 2, padding: "0 1px" }}>
        {part}
      </mark>
    ) : (
      part
    )
  );
}
