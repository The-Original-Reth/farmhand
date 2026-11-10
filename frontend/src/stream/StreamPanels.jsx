import { useState } from "react";
import { Eye, EyeOff, Radio } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, linkButton, monoText, panelBox, primaryButton, uiText } from "../styles.js";
import { heading, help, panel } from "./streamStyles.js";
import { saveYouTubeClient, youtubeApply, youtubeSignIn, youtubeSignOut } from "../api.js";

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

// The YouTube broadcast's own title and description (saved with the page's Save; set on YouTube once the broadcast
// starts, or straight away while live), and signing Farmhand in to the channel, which setting them needs.
export function YouTubeTextPanel({ shown, change, status }) {
  const title = status.title;
  return (
    <div data-testid="stream-youtube-panel" style={panel()}>
      <div style={heading}>YouTube title and description</div>
      <label style={uiText(12, c.textMuted, { display: "flex", flexDirection: "column", gap: 4 })}>
        <span>
          Title <span style={uiText(11, c.textFaint)}>{shown.title.length}/100</span>
        </span>
        <input
          data-testid="stream-title" value={shown.title} maxLength={100} onChange={(e) => change({ title: e.target.value })}
          placeholder="Left empty, YouTube's own title stays" style={{ ...fieldBox(), padding: "6px 8px" }}
        />
      </label>
      <label style={uiText(12, c.textMuted, { display: "flex", flexDirection: "column", gap: 4 })}>
        Description
        <textarea
          data-testid="stream-description" value={shown.description} maxLength={5000} rows={4} onChange={(e) => change({ description: e.target.value })}
          placeholder="Left empty, YouTube's own description stays" style={{ ...fieldBox(), padding: "6px 8px", resize: "vertical", lineHeight: 1.5 }}
        />
      </label>
      {title && (
        <div data-testid="stream-title-status" style={uiText(12, title.state === "failed" ? c.danger : title.state === "done" ? c.green : c.amber, { lineHeight: 1.5 })}>
          {title.message}
        </div>
      )}
      {!title && <div style={help}>Set on the YouTube broadcast once it starts; needs the YouTube account below signed in.</div>}
    </div>
  );
}

// A client ID or secret: dots until the eye next to it is clicked. `testid`: the field's; its eye's is `${testid}-show`.
function HiddenField({ testid, value, onChange, placeholder }) {
  const [shown, setShown] = useState(false);
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
      <input
        data-testid={testid} type={shown ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off"
        placeholder={placeholder} style={{ ...fieldBox(), padding: "6px 8px", flex: 1, minWidth: 0 }}
      />
      <button
        type="button" data-testid={`${testid}-show`} onClick={() => setShown(!shown)} aria-label={shown ? "Hide" : "Show"} title={shown ? "Hide it" : "Show it"}
        style={{ ...headerButton(), padding: "0 7px" }}
      >
        {shown ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  );
}

// The saved client ID, as dots until the eye is clicked
function HiddenText({ value }) {
  const [shown, setShown] = useState(false);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, flex: 1, minWidth: 200 }}>
      <span data-testid="stream-youtube-client-shown" style={uiText(12, c.textMuted, { wordBreak: "break-all" })}>
        Client: {shown ? value : "•".repeat(Math.min(24, (value || "").length || 12))}
      </span>
      <button
        type="button" data-testid="stream-youtube-client-show" onClick={() => setShown(!shown)} aria-label={shown ? "Hide" : "Show"} title={shown ? "Hide it" : "Show it"}
        style={{ ...headerButton(), padding: "0 7px" }}
      >
        {shown ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </span>
  );
}

// The step-by-step guide to connecting the channel, on a page of its own (YouTubeGuide.jsx), in a new tab
const GUIDE_URL = "/help/youtube";
const GuideLink = () => (
  <a data-testid="stream-youtube-guide" href={GUIDE_URL} target="_blank" rel="noreferrer" style={uiText(12, c.amber, { textDecoration: "underline" })}>
    How to connect your YouTube channel, step by step
  </a>
);

// Signing Farmhand in to the YouTube channel, which setting the title and description needs; while live, setting them
// again straight away.
export function YouTubeAccountPanel({ youtube, status, ask, busy }) {
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [editingClient, setEditingClient] = useState(false);
  const showClientForm = !youtube.clientSet || editingClient;
  const saveClient = () =>
    ask("youtube", () => saveYouTubeClient({ clientId: clientId.trim() || youtube.clientId, clientSecret: secret.trim() })).then(
      (p) => p && (setClientId(""), setSecret(""), setEditingClient(false)),
    );
  return (
    <div data-testid="stream-youtube-account" style={panel()}>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <div style={heading}>YouTube account</div>
          <GuideLink />
        </div>
        {youtube.signedIn ? (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={uiText(13, c.green, { flex: 1 })}>Signed in{youtube.channel ? ` as ${youtube.channel}` : ""}</span>
            {status.live && (
              <button type="button" data-testid="stream-youtube-apply" onClick={() => ask("youtube", youtubeApply)} disabled={!!busy} style={headerButton()}>
                {busy === "youtube" ? "Setting…" : "Set title on YouTube now"}
              </button>
            )}
            <button type="button" data-testid="stream-youtube-sign-out" onClick={() => ask("youtube", () => youtubeSignOut(false))} disabled={!!busy} style={headerButton()}>
              Sign out
            </button>
          </div>
        ) : youtube.signingIn ? (
          <div data-testid="stream-youtube-code" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={uiText(13, c.textPrimary, { lineHeight: 1.6 })}>
              Open{" "}
              <a href={youtube.signingIn.verificationUrl} target="_blank" rel="noreferrer" style={{ color: c.amber }}>
                {youtube.signingIn.verificationUrl.replace(/^https?:\/\//, "")}
              </a>{" "}
              on any computer or phone, sign in to the Google account that owns the channel, and enter this code:
            </div>
            <div style={monoText(22, c.heading, { letterSpacing: 2 })}>{youtube.signingIn.userCode}</div>
            <div style={help}>This page notices by itself once you've entered it.</div>
          </div>
        ) : showClientForm ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={help}>
              Setting the title needs Farmhand signed in to your channel, once: make a small app in Google Cloud (a{" "}
              <b>TVs and Limited Input devices</b> client) and paste its client ID and secret here. The guide above goes through it
              step by step.
            </div>
            <HiddenField
              testid="stream-youtube-client-id" value={clientId} onChange={setClientId}
              placeholder={youtube.clientSet ? "Client ID (saved; type to replace)" : "Client ID (…apps.googleusercontent.com)"}
            />
            <HiddenField
              testid="stream-youtube-secret" value={secret} onChange={setSecret}
              placeholder={youtube.clientSet ? "Client secret (saved; type to replace)" : "Client secret"}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button" data-testid="stream-youtube-save-client" onClick={saveClient} disabled={!!busy || (!clientId.trim() && !youtube.clientSet)}
                style={headerButton()}
              >
                {busy === "youtube" ? "Saving…" : "Save client"}
              </button>
              {editingClient && (
                <button type="button" onClick={() => setEditingClient(false)} style={cancelButton()}>
                  Cancel
                </button>
              )}
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <HiddenText value={youtube.clientId} />
            <button type="button" onClick={() => setEditingClient(true)} style={linkButton(12)}>
              Change
            </button>
            <button type="button" data-testid="stream-youtube-sign-in" onClick={() => ask("youtube", youtubeSignIn)} disabled={!!busy} style={headerButton()}>
              {busy === "youtube" ? "Asking Google…" : "Sign in to YouTube"}
            </button>
          </div>
        )}
        {youtube.error && <div style={uiText(12, c.danger, { lineHeight: 1.5 })}>{youtube.error}</div>}
      </div>
    </div>
  );
}

const WHERE_KEY = {
  youtube: "In YouTube Studio: Create → Go live → Stream, then Copy next to Stream key.",
};
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
                    ? ` · Collecting the ${status.delay.seconds} s delay before sending to YouTube (${Math.round(status.delay.held)} s so far)`
                    : ` · ${Math.round(status.delay.held)} s of the ${status.delay.seconds} s delay held`
                  : ""}`
              : off
                ? "The stream is off: ffmpeg isn't running on the server. Set everything up as usual, and turn it on above to go live."
                : `Farmhand sends the grid below to ${destLabel(destination)} itself, no OBS needed.`}
        </div>
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

// Where it goes, and its stream key (typed here once, kept on the server: `keySet` says one is saved)
// `delay`, `onDelay`: seconds the stream is held before YouTube gets it (saved with Save; applies when going live).
export function WhereToPanel({ destination, destinations, onDestination, streamKey, onKey, keySet, onForgetKey, busy, delay = 60, onDelay, live = false }) {
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
      <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" })}>
        <span style={{ width: 90 }}>Stream key</span>
        <input
          data-testid="stream-key" type="password" autoComplete="new-password" name="farmhand-stream-key" value={streamKey} onChange={(e) => onKey(e.target.value)}
          placeholder={keySet ? "Saved. Type a new one to replace it" : "Paste your stream key"}
          style={{ ...fieldBox(), padding: "6px 8px", flex: 1, minWidth: 240 }}
        />
        {keySet && (
          <button type="button" data-testid="stream-forget-key" onClick={onForgetKey} disabled={!!busy} style={headerButton()}>
            Forget key
          </button>
        )}
      </label>
      <div style={help}>{WHERE_KEY[destination]} The key stays in Farmhand: it isn't shown again or written to the settings copy.</div>
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
