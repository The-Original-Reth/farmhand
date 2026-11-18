import { c } from "../theme.js";
import { fieldBox, uiText } from "../styles.js";
import { heading, help, panel } from "./streamStyles.js";

// Stream control's panels: taking turns (LayoutPanel, the stream plugins' own), and what each site is told: the title,
// the description and the stream delay (WordsPanel).

const seconds = (v) => (v === "" || v == null ? "" : Number(v));

// The whole grid all the time, or taking turns: the grid for secondsAll (0: never), then each camera on its own for
// secondsEach, in square order. `count`: how many cameras are in the grid.
// `shown`: the settings as changed on the page; `change(what)` changes them (saved with the page's Save).
// (The resolution is chosen above the preview; what it costs the computer is said here.)
export function LayoutPanel({ shown, count, change, bare = false }) {
  const cycle = shown.layout === "cycle";
  const all = Number(shown.secondsAll) || 0;
  const each = Number(shown.secondsEach) || 0;
  const round = all + count * each;
  const numberBox = { ...fieldBox(), padding: "5px 8px", width: 80 };
  return (
    <div data-testid="stream-layout-panel" style={bare ? { display: "flex", flexDirection: "column", gap: 12 } : panel()}>
      <div style={bare ? uiText(13, c.heading, { fontWeight: 600 }) : heading}>Layout</div>
      {shown.resolution !== "720p" && (
        <div style={help}>
          {shown.resolution === "1080p"
            ? "1080p is sharp, and fine on a PC or the Proxmox container; on a Raspberry Pi, 720p is safer with several cameras."
            : "2K is the sharpest, and the most work for the computer: best on a PC or the Proxmox container."}
        </div>
      )}
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8 })}>
        <input type="radio" name="stream-layout" checked={!cycle} onChange={() => change({ layout: "grid" })} />
        The whole grid, all the time
      </label>
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8 })}>
        <input data-testid="stream-cycle" type="radio" name="stream-layout" checked={cycle} onChange={() => change({ layout: "cycle" })} />
        Take turns: the whole grid, then each camera on its own, round and round
      </label>
      {cycle && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingLeft: 24 }}>
          <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 8 })}>
            <span style={{ width: 150 }}>Stay on the whole grid</span>
            <input
              data-testid="stream-seconds-all" type="number" min={0} max={3600} value={shown.secondsAll}
              onChange={(e) => change({ secondsAll: seconds(e.target.value) })} style={numberBox}
            />
            seconds <span style={uiText(11, c.textFaint)}>(0: never)</span>
          </label>
          <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 8 })}>
            <span style={{ width: 150 }}>Stay on each camera</span>
            <input
              data-testid="stream-seconds-each" type="number" min={3} max={3600} value={shown.secondsEach}
              onChange={(e) => change({ secondsEach: seconds(e.target.value) })} style={numberBox}
            />
            seconds
          </label>
          <div style={help}>
            {count > 1
              ? `One round takes ${round >= 120 ? `${Math.floor(round / 60)} min ${round % 60} s` : `${round} s`}${all ? `: the whole grid for ${all} s, then each of the ${count} cameras for ${each} s.` : `: each of the ${count} cameras for ${each} s.`}`
              : "With one camera there's nothing to take turns with: the grid is shown all the time."}
          </div>
        </div>
      )}
    </div>
  );
}

// What each site shows with the stream, and the delay: the title and description (YouTube's broadcast and Twitch's
// channel take them when a stream plugin goes live), and how long each plugin holds the stream before its site gets it.
export function WordsPanel({ shown, change }) {
  const box = { ...fieldBox(), padding: "6px 8px", width: "100%" };
  return (
    <div data-testid="stream-control-words" style={panel()}>
      <div style={heading}>Title and description</div>
      <label style={uiText(12, c.textMuted, { display: "flex", flexDirection: "column", gap: 4 })}>
        Title
        <input data-testid="stream-control-title" maxLength={100} value={shown.title} onChange={(e) => change({ title: e.target.value })} style={box} />
      </label>
      <label style={uiText(12, c.textMuted, { display: "flex", flexDirection: "column", gap: 4 })}>
        Description
        <textarea
          data-testid="stream-control-description" maxLength={5000} rows={4} value={shown.description}
          onChange={(e) => change({ description: e.target.value })} style={{ ...box, resize: "vertical" }}
        />
      </label>
      <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" })}>
        <span>Stream delay</span>
        <input
          data-testid="stream-control-delay" type="number" min={0} max={120} step={5} value={shown.delay}
          onChange={(e) => change({ delay: e.target.value === "" ? "" : Number(e.target.value) })} style={{ ...fieldBox(), padding: "6px 8px", width: 80 }}
        />
        <span>seconds (0 to 120)</span>
      </label>
      <div style={help}>
        Each stream plugin uses this title and description on its site (a blank one leaves the site's own as it is), and holds this
        much of the stream before its site gets it, so a hiccup shorter than that never reaches viewers. A plugin's own settings
        (its stream key, sign-in, YouTube privacy or Twitch category) stay on its own page.
      </div>
    </div>
  );
}

