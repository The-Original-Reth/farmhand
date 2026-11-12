import { Radio } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, panelBox, primaryButton, uiText } from "../styles.js";
import { heading, help, panel } from "./streamStyles.js";

// The Stream page's panels: its on/off switch, on air or not, where it goes, taking turns, and the YouTube broadcast's
// title and description.

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

const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");

// The switch at the top of the page: the stream's functions on or off
export function StreamSwitch({ on, onTurn, busy }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span style={uiText(14, c.heading, { fontWeight: 600 })}>Stream</span>
      <button
        type="button" role="switch" aria-checked={on} data-testid="stream-switch" disabled={busy} onClick={() => onTurn(!on)}
        title={on ? "Turn the stream off: ffmpeg stops on the server (the page still works)" : "Turn the stream on, to go live"}
        style={{
          position: "relative", width: 40, height: 22, borderRadius: 11, border: `1px solid ${on ? c.green : c.borderStrong}`, padding: 0,
          background: on ? c.green : c.panelAlt, cursor: busy ? "default" : "pointer", flexShrink: 0,
        }}
      >
        <span style={{ position: "absolute", top: 2, left: on ? 20 : 2, width: 16, height: 16, borderRadius: 8, background: on ? c.bg : c.textMuted, transition: "left 0.15s" }} />
      </button>
      <span style={uiText(12, on ? c.textMuted : c.textFaint)}>{on ? "On" : "Off"}</span>
    </div>
  );
}

// Mute, beside the stream's switch: the music silent on this page only (the stream keeps playing it). Kept in this
// browser.
export function MuteSwitch({ muted, onMute }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span style={uiText(14, c.heading, { fontWeight: 600 })}>Mute</span>
      <button
        type="button" role="switch" aria-checked={muted} data-testid="stream-mute" onClick={() => onMute(!muted)}
        title={muted ? "Unmute the music on this page" : "Mute the music on this page only: the stream keeps playing it"}
        style={{
          position: "relative", width: 40, height: 22, borderRadius: 11, border: `1px solid ${muted ? c.amber : c.borderStrong}`, padding: 0,
          background: muted ? c.amber : c.panelAlt, cursor: "pointer", flexShrink: 0,
        }}
      >
        <span style={{ position: "absolute", top: 2, left: muted ? 20 : 2, width: 16, height: 16, borderRadius: 8, background: muted ? c.bg : c.textMuted, transition: "left 0.15s" }} />
      </button>
      <span style={uiText(12, muted ? c.amber : c.textFaint)}>{muted ? "Music muted here" : "Music heard here"}</span>
    </div>
  );
}

// On air or not, and the button that changes it. `destLabel(key)`: a destination's name; `destination`: the one chosen;
// `off`: the switch at the top is off, so there's no going live until it's on.
export function LiveStatusPanel({ status, destLabel, destination, busy, onStart, onStop, off = false }) {
  const on = status.encoder === "nvenc" ? " · on the NVIDIA card" : status.encoder === "cpu" ? " · on the processor" : "";
  return (
    <div data-testid="stream-status" style={panelBox({ padding: 16, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" })}>
      <Radio size={20} color={status.live ? (status.error ? c.amber : c.green) : c.textFaint} />
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={uiText(15, c.heading, { fontWeight: 600 })}>
          {status.live ? (status.error ? "Reconnecting…" : `Live on ${destLabel(status.destination)} since ${timeOf(status.startedAt)}${on}`) : "Not streaming"}
        </div>
        <div style={uiText(12, status.error ? c.amber : c.textMuted, { marginTop: 4, lineHeight: 1.5 })}>
          {status.error
            ? status.error
            : status.live
              ? `${status.cameras.length} camera${status.cameras.length === 1 ? "" : "s"}: ${status.cameras.join(", ")}${
                status.delay
                  ? status.delay.filling
                    ? status.holding
                      ? ` · Back after a restart: YouTube is shown the holding screen while the ${status.delay.seconds} s delay fills (${Math.round(status.delay.held)} s so far)`
                      : ` · Collecting the ${status.delay.seconds} s delay before sending to YouTube (${Math.round(status.delay.held)} s so far)`
                    : ` · ${Math.round(status.delay.held)} s of the ${status.delay.seconds} s delay held`
                  : ""}${status.changing ? " · Changing to the new layout: it takes over in a few seconds, with no break" : ""}`
              : off
                ? "The stream is off: ffmpeg isn't running on the server. Set everything up as usual, and turn it on above to go live."
                : `Farmhand sends the grid below to ${destLabel(destination)} itself, no OBS needed.`}
        </div>
        {status.live && status.youtube && <YouTubeLiveLine yt={status.youtube} />}
        {status.live && status.selfCheck && (
          <div data-testid="stream-self-check" style={uiText(12, c.amber, { marginTop: 6, lineHeight: 1.5 })}>
            {timeOf(status.selfCheck.at)}: {status.selfCheck.message}
          </div>
        )}
      </div>
      {status.live ? (
        <button type="button" data-testid="stream-stop" onClick={onStop} disabled={!!busy} style={{ ...cancelButton(!!busy), color: c.danger, borderColor: c.danger }}>
          {busy === "stop" ? "Stopping…" : "Stop stream"}
        </button>
      ) : (
        <button
          type="button" data-testid="stream-start" onClick={onStart} disabled={!!busy || off} style={primaryButton(!!busy || off)}
          title={off ? "Turn the stream on (top of the page) to go live" : undefined}
        >
          {busy === "start" ? "Going live…" : "Go live"}
        </button>
      )}
    </div>
  );
}

const HEALTH = { good: ["Healthy", "green"], ok: ["OK", "green"], bad: ["Poor", "amber"], noData: ["Not receiving video yet", "amber"] };
const STATE = { created: "being set up", ready: "waiting for the video", testStarting: "starting", testing: "testing", liveStarting: "starting",
  live: "live", complete: "ended", revoked: "taken down", gone: "gone" };

// What YouTube says of the broadcast Farmhand made (read about once a minute): its state, health, viewers, and links
function YouTubeLiveLine({ yt }) {
  const [healthWord, tone] = HEALTH[yt.health] || ["Asking YouTube…", "textMuted"];
  return (
    <div data-testid="stream-youtube-live" style={uiText(12, c.textMuted, { marginTop: 6, lineHeight: 1.5 })}>
      <span>
        YouTube: <span style={{ color: c[tone], fontWeight: 600 }}>{healthWord}</span>
        {yt.state ? ` · broadcast ${STATE[yt.state] || yt.state}` : ""}
        {yt.viewers !== null ? ` · ${yt.viewers} watching` : ""}
        {" · "}
        <a href={yt.watchUrl} target="_blank" rel="noreferrer" style={{ color: c.link }}>Watch</a>
        {" · "}
        <a href={yt.studioUrl} target="_blank" rel="noreferrer" style={{ color: c.link }}>Chat and analytics in YouTube Studio</a>
      </span>
      {yt.issues.map((i) => <div key={i} style={{ color: c.amber }}>{i}</div>)}
    </div>
  );
}

// Where it goes, and the stream's delay (the stream key and the rest of YouTube are in the YouTube settings window)
// `delay`, `onDelay`: seconds the stream is held before YouTube gets it (saved with Save; applies when going live).
// `youtubeSettings`: the YouTube settings button and its summary (the stream key, title and account are in its window).
export function WhereToPanel({ destination, destinations, onDestination, delay = 60, onDelay, live = false, youtubeSettings = null }) {
  return (
    <div style={panel()}>
      <div style={heading}>Where to</div>
      <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 10 })}>
        <span style={{ width: 90 }}>Stream to</span>
        {/* a choice only once there's more than one (YouTube Live for now) */}
        {destinations.length > 1 ? (
          <select data-testid="stream-destination" value={destination} onChange={(e) => onDestination(e.target.value)} style={{ ...fieldBox(), padding: "6px 8px" }}>
            {destinations.map((d) => (
              <option key={d.key} value={d.key}>{d.label}</option>
            ))}
          </select>
        ) : (
          <span data-testid="stream-destination" style={uiText(13, c.text)}>{destinations[0]?.label}</span>
        )}
      </label>
      {youtubeSettings}
      <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" })}>
        <span style={{ width: 90 }}>Stream delay</span>
        <input
          data-testid="stream-delay" type="number" min={0} max={120} step={5} value={delay}
          onChange={(e) => onDelay(e.target.value === "" ? "" : Number(e.target.value))} style={{ ...fieldBox(), padding: "6px 8px", width: 80 }}
        />
        <span>seconds (0 to 120)</span>
      </label>
      <div style={help}>
        Farmhand holds this much of the stream before YouTube gets it, so a hiccup shorter than that (a camera, the processor
        falling behind for a moment) never reaches viewers. They see everything this much later.
        {live ? " A new delay applies the next time you go live." : ""}
      </div>
    </div>
  );
}
