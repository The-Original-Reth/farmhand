import { useEffect, useState } from "react";
import { c, fixed, fs, ui } from "../theme.js";
import { fieldBox, headerButton, uiText } from "../styles.js";
import { GridSize } from "./StreamSquares.jsx";
import { StreamFonts } from "./CardScreen.jsx";
import { Screen } from "./PreviewScreen.jsx";
import { BORDER_PX, swapped, turnAt } from "./shapes.js";
import { useSecondsSince, useServerClock, useSlidePlayer } from "./previewClocks.js";
import { SquareEditor } from "./SquareEditor.jsx";

// What the stream looks like, and where its grid is set up. Above it: the grid's size and the resolution. In it: the
// grid's squares as the server lays them out, the cameras playing in this browser (as on Monitor, so it shows even while
// not live; the stream itself is made on the server), each logo in its square, an empty square black, each with its
// border, and the words the server writes under each camera. Click a square to choose what's in it (the editor under
// the preview); drag a square onto another to swap them. While a square is being edited or dragged, taking turns waits
// on the whole grid.
//
// `shown`: the page's choices (cols, rows, cells, resolution...); `change(what)` changes them. `squares`: the cells as
// played, row by row: { type: "camera", key, label, cam (as /webcams gives it, or null when not found), print,
// background (its own colour round it, or null: the stream's) } |
// { type: "card", cell } | null. `borderColor`: "#RRGGBB" (the person's own choice, so not from the palette);
// `cycle`: taking turns, { all, each } seconds (null: the whole grid all the time), on this page's own clock;
// `cameras`, `media` (the stream folder's pictures and slideshows), `label`: what a square can hold, for its editor
// (SquareEditor.jsx), which also uploads and deletes pictures (`ask`, `busy`: the page's own way of asking the server)
// and saves the page (`onSave`; `dirty`: something isn't saved yet).

export function StreamPreview({ shown, change, squares, showStatus, live, cycle = null, resolutions = [], cameras = [], media = { images: [], slideshows: [] }, fonts = [], label, ask, busy, onSave, dirty, onRenameSlideshow, serverClock = null, onRevert }) {
  const { cols, rows, cells, borderColor } = shown;
  const back = shown.background || "#000000"; // the stream's own colour (the person's choice, so not from the palette)
  const words = { font: shown.font, color: shown.color }; // the stream's words, every square's unless it has its own
  const inset = (BORDER_PX * rows) / 720; // a square's border, as a part of its height: pictures are fitted inside it
  const [selected, setSelected] = useState(null); // the square being edited: its place
  const [dragging, setDragging] = useState(null); // the square being dragged: its place
  const [over, setOver] = useState(null); // the square it would go to
  const cameraSquares = squares.map((sq, i) => (sq?.type === "camera" ? i : null)).filter((i) => i !== null);
  const n = cameraSquares.length;
  const editing = selected !== null || dragging !== null;
  const turning = !!cycle && n > 1;
  const seconds = useSecondsSince(turning, [cycle?.all, cycle?.each, n]);
  // the slideshow in the square being edited: the square here and the editor's canvas show the same picture
  const edited = selected !== null && squares[selected]?.type === "card" ? squares[selected].cell : null;
  const editedShow = edited?.slideshow ? media.slideshows.find((x) => x.name === edited.slideshow) : null;
  const slideCtl = useSlidePlayer(editedShow?.images.length || 0, edited?.seconds, selected, !!editedShow);
  useEffect(() => {
    if (selected !== null && selected >= cells.length) setSelected(null); // the grid got smaller
  }, [cells.length, selected]);
  // with nothing changed here, the preview keeps the server's time of day (null: its own)
  const clock = useServerClock(serverClock);
  const { one, left } = turnAt(clock !== null ? Math.floor(clock) : seconds, n, turning && !editing ? cycle : null);
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
      <StreamFonts fonts={fonts} />
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8, flexWrap: "wrap" }}>
        <div style={uiText(14, c.heading, { fontWeight: 600 })}>Preview</div>
        {/* whether it shows what the server does (or will, going live): only with nothing changed and not saved */}
        <span
          data-testid="stream-in-step"
          title={clock !== null ? "Slideshows and taking turns keep the server's time of day, as the stream does" : "Changes not saved yet: the preview plays them on its own time"}
          style={uiText(11, clock !== null ? c.green : c.amber, { border: `1px solid ${clock !== null ? c.green : c.amber}`, borderRadius: 3, padding: "1px 6px", whiteSpace: "nowrap" })}
        >
          {clock === null ? "Not in step: save to match the server" : serverClock.live ? "In step with the stream" : "In step with the server"}
        </span>
        {live && (
          <span style={{ ...ui, fontSize: fs(11), fontWeight: 700, letterSpacing: 0.5, color: c.danger, border: `1px solid ${c.danger}`, borderRadius: 3, padding: "1px 6px" }}>
            LIVE
          </span>
        )}
        <div style={{ flex: 1 }} />
        <button
          type="button" data-testid="stream-revert" onClick={onRevert} disabled={!dirty || !onRevert} style={headerButton()}
          title="Back to the last saved setup: every change not saved yet goes"
        >
          Revert
        </button>
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
          // the square being edited: its picture and words move here too, so it isn't dragged as a whole
          const editHere = selected === i && sq?.type === "card" && alone === null;
          return (
            <div
              key={key} data-testid="stream-preview-square" draggable={alone === null && !editHere}
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
                <Screen
                  sq={sq} showStatus={showStatus} big={alone === i} media={media} back={back} words={words} clock={clock} inset={alone === i ? 0 : inset} edit={editHere && "quiet"} slide={selected === i ? slideCtl : null}
                  onChange={(what) => change({ cells: cells.map((x, j) => (j === i ? { ...x, ...what } : x)) })}
                />
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
          cells={cells} i={selected} onCells={(next) => change({ cells: next })} cameras={cameras} media={media} fonts={fonts} label={label} streamBackground={back} streamText={words} inset={inset} slide={slideCtl}
          aspect={(16 * rows) / (9 * cols)} onSave={onSave} dirty={dirty} saving={busy === "save"}
          showStatus={showStatus} ask={ask} busy={busy} onRenameSlideshow={onRenameSlideshow} onDone={() => setSelected(null)} screen={<Screen sq={squares[selected]} showStatus={showStatus} big media={media} back={back} words={words} />}
        />
      ) : (
        <div style={uiText(12, c.textMuted, { marginTop: 6 })}>
          {turning && !editing ? `Now: ${one === null ? "the whole grid" : `${squares[alone].label} (${one + 1} of ${n})`} · next in ${left} s. ` : ""}
          Click a square to choose what's in it; drag one onto another to swap them. In the square being edited, drag its picture or words to move them.
        </div>
      )}
      <div style={uiText(11, c.textFaint, { marginTop: 6, lineHeight: 1.5 })}>
        {clock !== null && serverClock.live
          ? "In step with the stream: the same slideshow pictures and turns as the picture the server is sending (YouTube shows it a few seconds later)."
          : clock !== null
            ? "In step with the server: going live, the stream starts on the slideshow pictures and turn shown here."
          : "Played in this browser, so you can check it before going live. What goes out is made on the server and may lag a few seconds behind."}
      </div>
    </div>
  );
}
