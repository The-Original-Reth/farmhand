import { c } from "../theme.js";
import { MAX_SIDE, autoGrid, fontFamily, resized } from "./shapes.js";
import { heading, help, panel, subheading } from "./streamStyles.js";
import { LayoutPanel } from "./StreamPanels.jsx";
import { fieldBox, headerButton, uiText } from "../styles.js";

// The Stream page's grid. The grid is 1x1 to 5x5 squares; each holds a camera, words, an image, a slideshow or nothing
// (chosen in the preview's square editor, SquareEditor.jsx, and swapped by dragging in the preview). Every square has a
// border round it, in a colour of your choosing.
const SIDES = [1, 2, 3, 4, 5];

const part = { display: "flex", flexDirection: "column", gap: 12 };

// The grid's size, above the preview: 1 to 5 squares across and down. Squares that still fit keep their place.
export function GridSize({ shown, change }) {
  const { cols, rows, cells } = shown;
  const setSize = (nextCols, nextRows) => change({ cols: nextCols, rows: nextRows, cells: resized(cells, { cols, rows }, nextCols, nextRows) });
  const box = { ...fieldBox(), padding: "4px 6px" };
  return (
    <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6 })}>
      Grid
      <select data-testid="stream-cols" value={cols} onChange={(e) => setSize(Number(e.target.value), rows)} style={box} title="Squares across">
        {SIDES.map((n) => <option key={n} value={n}>{n}</option>)}
      </select>
      ×
      <select data-testid="stream-rows" value={rows} onChange={(e) => setSize(cols, Number(e.target.value))} style={box} title="Squares down">
        {SIDES.map((n) => <option key={n} value={n}>{n}</option>)}
      </select>
    </label>
  );
}

// The rest of the grid's choices (the squares themselves are set in the preview): filling it with every camera,
// emptying it, the words under each camera, the stream's background colour (each square's unless it has its own) and the
// border's colour. `cameras`: every camera there is, [{ key, label }];
// `change(what)` changes the page's choices (saved with its Save).
export function SquaresPanel({ shown, change, cameras, finding, bare = false }) {
  const { cols, rows, cells } = shown;
  const placed = new Set(cells.filter((x) => x?.camera).map((x) => x.camera));
  // every camera not in a square yet goes into the empty ones, the grid growing (up to 5x5) when they don't all fit
  const fillAll = () => {
    const missing = cameras.map((x) => x.key).filter((k) => !placed.has(k));
    const needed = cells.filter(Boolean).length + missing.length;
    let size = { cols, rows };
    if (needed > cols * rows) size = autoGrid(Math.min(needed, MAX_SIDE * MAX_SIDE));
    const next = resized(cells, { cols, rows }, size.cols, size.rows);
    for (let i = 0; i < next.length && missing.length; i++) if (!next[i]) next[i] = { camera: missing.shift() };
    change({ cols: size.cols, rows: size.rows, cells: next });
  };

  return (
    <div data-testid="stream-squares" style={bare ? part : panel()}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ ...(bare ? subheading : heading), flex: 1 }}>
          Squares <span style={uiText(12, c.textFaint, { fontWeight: 400 })}>{cols}×{rows} · {placed.size} camera{placed.size === 1 ? "" : "s"}</span>
        </div>
        <button type="button" data-testid="stream-fill" onClick={fillAll} disabled={!cameras.length} style={headerButton()}>
          Add all cameras
        </button>
        <button type="button" data-testid="stream-clear" onClick={() => change({ cells: cells.map(() => null) })} style={headerButton()}>
          Clear
        </button>
      </div>
      {finding && <div style={help}>Finding the printers' cameras…</div>}
      <div style={help}>
        In the preview, click a square to choose what's in it, and drag a square onto another to swap them. Taking turns goes
        through the cameras in square order.
      </div>
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8 })}>
        <input data-testid="stream-show-status" type="checkbox" checked={shown.showStatus} onChange={(e) => change({ showStatus: e.target.checked })} />
        Write each printer's name and print progress under its camera
      </label>
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" })}>
        <input
          data-testid="stream-background" type="color" value={(shown.background || "#000000").toLowerCase()} onChange={(e) => change({ background: e.target.value.toUpperCase() })}
          style={{ width: 34, height: 24, padding: 0, border: `1px solid ${c.border}`, background: "none", cursor: "pointer" }}
        />
        Background <span style={uiText(11, c.textFaint)}>{shown.background || "#000000"} · every square's, unless the square has its own</span>
        {(shown.background || "#000000") !== "#000000" && (
          <button type="button" onClick={() => change({ background: "#000000" })} style={headerButton()}>
            Black
          </button>
        )}
      </label>
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8 })}>
        <input
          data-testid="stream-border-color" type="color" value={shown.borderColor.toLowerCase()} onChange={(e) => change({ borderColor: e.target.value.toUpperCase() })}
          style={{ width: 34, height: 24, padding: 0, border: `1px solid ${c.border}`, background: "none", cursor: "pointer" }}
        />
        Border round each square <span style={uiText(11, c.textFaint)}>{shown.borderColor}</span>
        {shown.borderColor !== "#000000" && (
          <button type="button" onClick={() => change({ borderColor: "#000000" })} style={headerButton()}>
            Black
          </button>
        )}
      </label>
    </div>
  );
}

// Defaults: what every square and camera has unless it has its own, and how the grid is shown. The squares (filling
// and emptying the grid, the words on the cameras, the background and border colours), the stream's words' font and
// colour, and the layout (taking turns or not). `fonts`: [{ key, label }]; `count`: the cameras in the grid.
export function DefaultsPanel({ shown, change, cameras, finding, count, fonts }) {
  const row = uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" });
  return (
    <div data-testid="stream-defaults" style={panel()}>
      <div style={heading}>Defaults</div>
      <SquaresPanel shown={shown} change={change} cameras={cameras} finding={finding} bare />
      <label style={row}>
        Words
        <select
          data-testid="stream-font" value={shown.font || "play"} onChange={(e) => change({ font: e.target.value })}
          style={{ ...fieldBox(), padding: "5px 8px", fontFamily: fontFamily(shown.font) }}
        >
          {fonts.map((f) => <option key={f.key} value={f.key} style={{ fontFamily: fontFamily(f.key) }}>{f.label}</option>)}
        </select>
        <input
          data-testid="stream-color" type="color" value={(shown.color || "#FFFFFF").toLowerCase()} onChange={(e) => change({ color: e.target.value.toUpperCase() })}
          style={{ width: 34, height: 24, padding: 0, border: `1px solid ${c.border}`, background: "none", cursor: "pointer" }}
        />
        <span style={uiText(11, c.textFaint)}>every square's text and camera's words, unless it has its own</span>
      </label>
      <div style={{ borderTop: `1px solid ${c.border}` }} />
      <LayoutPanel shown={shown} count={count} change={change} bare />
    </div>
  );
}
