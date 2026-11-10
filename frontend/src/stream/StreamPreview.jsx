import { useEffect, useState } from "react";
import { c, fixed, fs, ui } from "../theme.js";
import { fieldBox, uiText } from "../styles.js";
import { CameraPicture } from "../monitor/players.jsx";
import { GridSize, swapped } from "./StreamSquares.jsx";
import { CardScreen, SquareEditor } from "./SquareEditor.jsx";

// What the stream looks like, and where its grid is set up. Above it: the grid's size and the resolution. In it: the
// grid's squares as the server lays them out, the cameras playing in this browser (as on Monitor, so it shows even while
// not live; the stream itself is made on the server), each logo in its square, an empty square black, each with its
// border, and the words the server writes under each camera. Click a square to choose what's in it (the editor under
// the preview); drag a square onto another to swap them. While a square is being edited or dragged, taking turns waits
// on the whole grid.
//
// `shown`: the page's choices (cols, rows, cells, resolution...); `change(what)` changes them. `squares`: the cells as
// played, row by row: { type: "camera", key, label, cam (as /webcams gives it, or null when not found), print } |
// { type: "card", cell } | null. `borderColor`: "#RRGGBB" (the person's own choice, so not from the palette);
// `cycle`: taking turns, { all, each } seconds (null: the whole grid all the time), on this page's own clock;
// `cameras`, `media` (the stream folder's pictures and slideshows), `label`: what a square can hold, for its editor
// (SquareEditor.jsx),
// which also uploads and deletes logos (`ask`, `busy`: the page's own way of asking the server).

// what's written under a camera, as the server writes it (services/live_stream.py status_line)
export const statusLine = (label, p) => {
  if (!p?.state) return `${label} · Idle`;
  let line = `${label} · ${p.state === "paused" ? "Paused" : "Printing"}`;
  if (typeof p.progress === "number") line += ` ${Math.round(p.progress)}%`;
  if (p.file) line += ` · ${String(p.file).split("/").pop().slice(0, 60)}`;
  return line;
};

// Which camera is on its own now, taking turns: its place among the cameras, or null while the whole grid is shown; and
// how long until the next turn. As the server works it out (services/live_stream.py windows).
export const turnAt = (seconds, n, cycle) => {
  if (!cycle || n < 2) return { one: null, left: null };
  const period = cycle.all + n * cycle.each;
  const at = seconds % period;
  if (at < cycle.all) return { one: null, left: cycle.all - at };
  const one = Math.floor((at - cycle.all) / cycle.each);
  return { one, left: cycle.all + (one + 1) * cycle.each - at };
};

export function StreamPreview({ shown, change, squares, showStatus, live, cycle = null, resolutions = [], cameras = [], media = { images: [], slideshows: [] }, label, ask, busy }) {
  const { cols, rows, cells, borderColor } = shown;
  const back = shown.background || "#000000"; // the stream's own colour (the person's choice, so not from the palette)
  const [selected, setSelected] = useState(null); // the square being edited: its place
  const [dragging, setDragging] = useState(null); // the square being dragged: its place
  const [over, setOver] = useState(null); // the square it would go to
  const cameraSquares = squares.map((sq, i) => (sq?.type === "camera" ? i : null)).filter((i) => i !== null);
  const n = cameraSquares.length;
  const [seconds, setSeconds] = useState(0);
  const editing = selected !== null || dragging !== null;
  const turning = !!cycle && n > 1;
  useEffect(() => {
    if (!turning) return;
    setSeconds(0);
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [turning, cycle?.all, cycle?.each, n]);
  useEffect(() => {
    if (selected !== null && selected >= cells.length) setSelected(null); // the grid got smaller
  }, [cells.length, selected]);
  const { one, left } = turnAt(seconds, n, turning && !editing ? cycle : null);
  const alone = one === null ? null : cameraSquares[one]; // the square shown on its own, taking turns
  const drop = (to) => {
    if (dragging !== null && dragging !== to) {
      change({ cells: swapped(cells, dragging, to) });
      if (selected === dragging) setSelected(to);
      else if (selected === to) setSelected(dragging);
    }
    setDragging(null);
    setOver(null);
  };
  const what = (i) => {
    const sq = squares[i];
    if (sq?.type === "camera") return sq.label;
    if (sq?.type === "card") {
      const cd = sq.cell;
      const what = cd.slideshow ? `Slideshow “${cd.slideshow}”` : cd.image ? `Picture “${cd.image}”` : "Colour";
      return cd.text?.trim() ? `${what} with text` : what;
    }
    return "Empty";
  };

  return (
    <div data-testid="stream-preview">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8, flexWrap: "wrap" }}>
        <div style={uiText(14, c.heading, { fontWeight: 600 })}>Preview</div>
        <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6 })} title="Shows in empty squares, and round anything that doesn't fill its square">
          <input
            type="color" data-testid="stream-background" value={back.toLowerCase()} onChange={(e) => change({ background: e.target.value.toUpperCase() })}
            style={{ width: 30, height: 22, padding: 0, border: `1px solid ${c.border}`, background: "none", cursor: "pointer" }}
          />
          Background
        </label>
        {live && (
          <span style={{ ...ui, fontSize: fs(11), fontWeight: 700, letterSpacing: 0.5, color: c.danger, border: `1px solid ${c.danger}`, borderRadius: 3, padding: "1px 6px" }}>
            LIVE
          </span>
        )}
        <div style={{ flex: 1 }} />
        <GridSize shown={shown} change={change} />
        <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6 })}>
          Resolution
          <select
            data-testid="stream-resolution" value={shown.resolution} onChange={(e) => change({ resolution: e.target.value })}
            style={{ ...fieldBox(), padding: "4px 6px" }}
          >
            {resolutions.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
          </select>
        </label>
      </div>
      <div
        data-testid="stream-preview-grid"
        style={{
          position: "relative", width: "100%", aspectRatio: "16 / 9", background: back, border: `1px solid ${c.border}`, borderRadius: 4,
          overflow: "hidden", display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
        }}
      >
        {/* each square placed by its row and column, and the cameras keyed by camera: moving one doesn't restart it, and
            all stay playing while one is on its own, so none has to connect again when its turn comes */}
        {squares.map((sq, i) => {
          const place = alone === i ? { gridColumn: "1 / -1", gridRow: "1 / -1" } : { gridColumn: (i % cols) + 1, gridRow: Math.floor(i / cols) + 1 };
          const key = sq?.type === "camera" ? sq.key : `${sq?.type || "empty"}-${i}`;
          const mark = selected === i || (over === i && dragging !== i) ? c.amber : null;
          return (
            <div
              key={key} data-testid="stream-preview-square" draggable={alone === null}
              onClick={() => setSelected(selected === i ? null : i)}
              onDragStart={(e) => {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", String(i));
                setDragging(i);
              }}
              onDragEnter={() => dragging !== null && setOver(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                drop(i);
              }}
              onDragEnd={() => (setDragging(null), setOver(null))}
              title={`Square ${i + 1}: ${what(i)}. Click to change it, drag to move it`}
              style={{
                position: "relative", minWidth: 0, minHeight: 0, overflow: "hidden", cursor: "pointer", opacity: dragging === i ? 0.4 : 1,
                display: alone !== null && alone !== i ? "none" : "flex", ...place,
              }}
            >
              {sq ? (
                <Screen sq={sq} showStatus={showStatus} big={alone === i} media={media} back={back} />
              ) : (
                <div style={{ ...ui, fontSize: fs(11), color: fixed.cameraMessage, margin: "auto" }}>{editing || squares.every((x) => !x) ? `${i + 1} · Empty` : ""}</div>
              )}
              {alone !== i && <div style={{ position: "absolute", inset: 0, border: `2px solid ${borderColor}`, pointerEvents: "none" }} />}
              {mark && <div style={{ position: "absolute", inset: 0, border: `3px solid ${mark}`, pointerEvents: "none" }} />}
            </div>
          );
        })}
      </div>
      {selected !== null && selected < cells.length ? (
        <SquareEditor
          cells={cells} i={selected} onCells={(next) => change({ cells: next })} cameras={cameras} media={media} label={label} streamBackground={back}
          ask={ask} busy={busy} onDone={() => setSelected(null)} screen={<Screen sq={squares[selected]} showStatus={showStatus} big media={media} back={back} />}
        />
      ) : (
        <div style={uiText(12, c.textMuted, { marginTop: 6 })}>
          {turning && !editing ? `Now: ${one === null ? "the whole grid" : `${squares[alone].label} (${one + 1} of ${n})`} · next in ${left} s. ` : ""}
          Click a square to choose what's in it; drag one onto another to swap them.
        </div>
      )}
      <div style={uiText(11, c.textFaint, { marginTop: 6, lineHeight: 1.5 })}>
        Played in this browser, so you can check it before going live. What goes out is made on the server and may lag a few seconds behind.
      </div>
    </div>
  );
}

// What a square shows: a camera, or a card (its colour, picture or slideshow, and words); nothing (the stream's colour)
// when null
function Screen({ sq, showStatus, big, media, back }) {
  if (!sq) return null;
  if (sq.type === "camera") return <CameraSquare sq={sq} showStatus={showStatus} big={big} />;
  if (sq.type === "card") return <CardScreen card={sq.cell} media={media} streamBackground={back} />;
  return null;
}

function CameraSquare({ sq, showStatus, big }) {
  const [state, setState] = useState("waiting"); // waiting | showing | failed
  const { cam, label } = sq;
  const turn = cam && [cam.rotation ? `rotate(${cam.rotation}deg)` : "", cam.flip_horizontal ? "scaleX(-1)" : "", cam.flip_vertical ? "scaleY(-1)" : ""].join(" ").trim();
  const fill = { width: "100%", height: "100%", objectFit: "contain", display: "block", border: 0, transform: turn || undefined, pointerEvents: "none" };
  const message = !cam ? "Camera not found" : state === "failed" ? "Camera not answering" : state === "waiting" ? "Connecting…" : null;
  return (
    <>
      {cam && <CameraPicture cam={cam} label={label} style={fill} onState={setState} />}
      {message && (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", ...ui, fontSize: fs(11), color: fixed.cameraMessage }}>
          {message}
        </div>
      )}
      {showStatus && (
        <div
          data-testid="stream-preview-words"
          style={{
            position: "absolute", left: 6, bottom: 8, maxWidth: "calc(100% - 12px)", padding: "2px 6px", background: fixed.cameraBadge, color: fixed.cameraText,
            ...ui, fontSize: fs(big ? 14 : 11), whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", pointerEvents: "none",
          }}
        >
          {statusLine(label, sq.print)}
        </div>
      )}
    </>
  );
}
