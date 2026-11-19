import { useState } from "react";
import { Radio, Settings } from "lucide-react";
import { pluginPageUrl } from "../api.js";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, primaryButton, uiText } from "../styles.js";
import { heading, help, panel } from "./streamStyles.js";

// The stream plugins (YouTube, Twitch...) that send the stream designed here, each with how its stream is doing and
// its own Start and Stop, and Start all / Stop all. A plugin is one when its manifest says it can be started from here
// (docs/plugins.md, stream_control). `streams`: as getStreamPlugins gives them; `busy`: what's being asked ("start:stream",
// "stop-all"...); `onStart(id)`, `onStop(id)`, `onAll("start" | "stop")`; `onOpenPlugin(id)` opens its own page;
// `onOpenPlugins` the Plugins page; `happened`: what the schedule did lately. Each has a tick box: which ones Stream
// control brings in (`onChoose(ids)`). One left out keeps its own layout, and isn't started or stopped from here.
// `onCopy(id)`: Copy layout, that stream's own layout made Stream control's (resolving once done).
// `media`: the stream folder as last found ({ error, on_share }); `onReconnect`: Reconnect NAS (its share connected again)
export function StreamsPanel({ streams, busy, onStart, onStop, onAll, onChoose, onCopy, onOpenPlugin, onOpenPlugins, happened = [], media = null, onReconnect }) {
  const usable = streams.filter((s) => s.enabled && s.chosen);
  const toggle = (id) => onChoose(streams.filter((s) => (s.id === id ? !s.chosen : s.chosen)).map((s) => s.id));
  const [copying, setCopying] = useState(false); // the Copy layout chooser open
  const anyLive = usable.some((s) => s.live);
  const allLive = usable.length > 0 && usable.every((s) => s.live);
  return (
    <div data-testid="stream-control-streams" style={panel()}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ ...heading, flex: 1 }}>Streams</div>
        <button
          type="button" data-testid="stream-control-copy-layout" onClick={() => setCopying(!copying)}
          disabled={!!busy || !streams.some((s) => s.enabled)} style={{ ...cancelButton(!!busy), ...(copying && { color: c.amber, borderColor: c.amber }) }}
          title="Take one stream's own layout and show it on all the streams"
        >
          Copy layout
        </button>
        <button
          type="button" data-testid="stream-control-start-all" onClick={() => onAll("start")} disabled={!!busy || !usable.length || allLive}
          style={primaryButton(!!busy || !usable.length || allLive)}
        >
          {busy === "start-all" ? "Going live…" : "Go live everywhere"}
        </button>
        <button
          type="button" data-testid="stream-control-stop-all" onClick={() => onAll("stop")} disabled={!!busy || !anyLive}
          style={{ ...cancelButton(!!busy || !anyLive), ...(anyLive && { color: c.danger, borderColor: c.danger }) }}
        >
          {busy === "stop-all" ? "Stopping…" : "Stop all"}
        </button>
      </div>
      {media?.error && (
        <div data-testid="stream-control-folder-away" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={uiText(12, c.amber, { flex: 1, minWidth: 200, lineHeight: 1.5 })}>
            The stream folder isn't available, so the streams can't get its pictures and music: {media.error}
          </span>
          {media.on_share && onReconnect && <ReconnectNas testid="stream-control-reconnect-nas" busy={busy} onReconnect={onReconnect} />}
        </div>
      )}
      <NasCopy copy={media?.copy} busy={busy} onReconnect={media?.on_share ? onReconnect : null} />
      {!streams.length && (
        <div style={help}>
          No stream plugin is added yet. Add the YouTube or Twitch stream plugin on the{" "}
          <button type="button" onClick={onOpenPlugins} style={{ ...uiText(12, c.amber), background: "none", border: "none", padding: 0, textDecoration: "underline", cursor: "pointer" }}>
            Plugins page
          </button>
          , and it shows here to start and stop.
        </div>
      )}
      {copying && <CopyLayout streams={streams.filter((s) => s.enabled)} busy={busy} onCopy={onCopy} onClose={() => setCopying(false)} />}
      {streams.length > 0 && (
        <div style={help}>Tick the streams Stream control brings in: they send this stream, and go live and stop from here.</div>
      )}
      {streams.map((s) => (
        <StreamRow key={s.id} s={s} busy={busy} onStart={onStart} onStop={onStop} onToggle={() => toggle(s.id)} onOpenPlugin={onOpenPlugin} />
      ))}
      <CameraStates cameras={camerasOf(streams)} />
      {happened.length > 0 && <LastScheduled h={happened[0]} />}
    </div>
  );
}

// A stream plugin's own settings window (YouTube settings, Twitch settings), as its own page opens it: its page shown
// from Farmhand at /plugins/<id>/, in a window of its own (brought forward when it's open already)
const openSiteSettings = (s) => {
  const w = window.open(pluginPageUrl(s.id, s.settingsPage), `farmhand-${s.id}-settings`, "popup,width=720,height=900");
  w?.focus();
};

// A plugin's problem kept short: a list of them ("a; b; c...", one per picture it couldn't copy, say) shows its first
// two and how many more; anything else past 300 characters is cut. The whole of it is in the row's tooltip.
const shortened = (text) => {
  if (!text) return text;
  const parts = text.split("; ");
  if (parts.length > 2) return `${parts.slice(0, 2).join("; ")}; and ${parts.length - 2} more like it`;
  return text.length > 300 ? `${text.slice(0, 300)}…` : text;
};

// Reconnect NAS: the network share the stream folder is on connected again
function ReconnectNas({ testid, busy, onReconnect }) {
  return (
    <button type="button" data-testid={testid} onClick={onReconnect} disabled={!!busy} style={headerButton()}>
      {busy === "reconnect" ? "Reconnecting…" : "Reconnect NAS"}
    </button>
  );
}

// How the stream folder's copy on the NAS is going (media.copy): Stream control works from Farmhand's own copy of its
// pictures and music, so the streams never wait on the NAS, and keeps the stream folder on the NAS in step with it.
// Nothing shown until that's how it works (the first copying from the NAS still under way: it works from the NAS).
const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null);
function NasCopy({ copy, busy, onReconnect }) {
  if (!copy?.working) return null;
  if (copy.error) {
    return (
      <div data-testid="stream-control-nas-copy" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={uiText(12, c.amber, { flex: 1, minWidth: 200, lineHeight: 1.5 })}>
          The streams carry on from Farmhand's own copy of the pictures and music, but the NAS copy isn't being kept up to date
          {copy.copied_at ? ` (last at ${clock(copy.copied_at)})` : ""}: {copy.error}
        </span>
        {onReconnect && <ReconnectNas testid="stream-control-nas-copy-reconnect" busy={busy} onReconnect={onReconnect} />}
      </div>
    );
  }
  return (
    <div data-testid="stream-control-nas-copy" style={uiText(12, c.textFaint, { lineHeight: 1.5 })}>
      Pictures and music are kept on Farmhand and copied to the stream folder on the NAS
      {copy.copying || copy.waiting ? ": copying now" : copy.copied_at ? `, last at ${clock(copy.copied_at)}` : ""}.
    </div>
  );
}

// Where a live stream's work is done, as its plugin says: the cameras unpacked and the stream compressed on the GPU (an
// NVIDIA card) or the CPU (the processor), and why the card isn't used for something it did before. Nothing from a
// plugin that doesn't say.
const ON = { gpu: "GPU", cpu: "CPU" };
function StreamHardware({ hw }) {
  if (!hw) return null;
  const { encoder, cameras } = hw;
  let text;
  if (encoder && encoder === cameras) text = `${ON[encoder]}: cameras and compressing`;
  else text = [cameras && `cameras on the ${ON[cameras]}`, encoder && `compressing on the ${ON[encoder]}`].filter(Boolean).join(", ");
  text = text.charAt(0).toUpperCase() + text.slice(1);
  return (
    <div
      data-testid="stream-control-hardware" data-encoder={encoder || ""} data-cameras={cameras || ""}
      title="Where the plugin does the stream's work: GPU is the NVIDIA card, CPU the processor"
      style={uiText(12, hw.note ? c.amber : c.textMuted, { lineHeight: 1.5 })}
    >
      {text}
      {hw.note ? ` · ${hw.note}` : ""}
    </div>
  );
}

// A live stream's delay, as its plugin holds it: how much of it is held, as words and a bar. While it's being collected
// again (after going live, or a stall used it up) the site is shown the holding screen meanwhile.
function StreamBuffer({ s }) {
  const b = s.buffer;
  if (!b) return null;
  if (!b.seconds) return <div data-testid="stream-control-buffer" style={uiText(12, c.textMuted)}>No delay: the stream goes to {s.site} as it's made</div>;
  const held = Math.round(b.held);
  const full = !b.filling && b.held >= b.seconds - 1;
  const words = b.filling
    ? `Delay filling: ${held} of ${Math.round(b.seconds)} s held${b.holding ? `, the holding screen on ${s.site} meanwhile` : ""}`
    : `Delay: ${held} of ${Math.round(b.seconds)} s held`;
  const tone = full ? c.green : c.amber;
  return (
    <div data-testid="stream-control-buffer" title={`How much of the stream is held back before ${s.site} gets it: a hiccup shorter than that never reaches viewers`} style={{ margin: "2px 0 4px" }}>
      <div style={uiText(12, full ? c.textMuted : c.amber, { lineHeight: 1.5 })}>{words}</div>
      <div style={{ height: 4, maxWidth: 220, background: c.border, borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${Math.min(100, (b.held / b.seconds) * 100)}%`, height: "100%", background: tone }} />
      </div>
    </div>
  );
}

function StreamRow({ s, busy, onStart, onStop, onToggle, onOpenPlugin }) {
  const mine = busy === `start:${s.id}` || busy === `stop:${s.id}`;
  let state;
  let tone = c.textMuted;
  if (!s.chosen) state = "Not brought in: it sends its own layout, and goes live from its own page";
  else if (!s.enabled) state = "Switched off on the Plugins page";
  else if (s.reachable === false) (state = s.error || "Not answering"), (tone = c.danger);
  else if (s.live) (state = s.error ? `Live, with a problem: ${s.error}` : "Live"), (tone = s.error ? c.amber : c.green);
  else if (s.error) (state = s.error), (tone = c.amber);
  else state = "Not streaming";
  // what keeps it from sending the stream designed here
  const notes = [];
  if (s.chosen && s.needsUpdate) notes.push("This version of the plugin sends its own layout: it goes live and stops from here, but needs an update to send this stream.");
  else if (s.chosen && s.enabled && !s.canReadDesign) notes.push("It wasn't given the stream:read permission, so it can't read this stream: add it again on the Plugins page and tick it.");
  else if (s.chosen && s.enabled && s.following === false) notes.push("It's set to send its own layout, not this one: switch it to Stream control on its own page.");
  return (
    <div data-testid="stream-control-stream" data-stream={s.id} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "8px 0", borderTop: `1px solid ${c.border}` }}>
      <input
        type="checkbox" data-testid="stream-control-choose" checked={s.chosen} disabled={!!busy} onChange={onToggle}
        aria-label={`Bring ${s.site} into Stream control`} title={s.chosen ? `Leave ${s.site} out of Stream control` : `Bring ${s.site} into Stream control`}
        style={{ marginTop: 3, flexShrink: 0, cursor: busy ? "default" : "pointer" }}
      />
      <Radio size={18} color={s.chosen && s.live ? (s.error ? c.amber : c.green) : c.textFaint} style={{ marginTop: 2, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0, opacity: s.chosen ? 1 : 0.65 }}>
        <div style={uiText(13, c.heading, { fontWeight: 600 })}>
          {s.site}
          <span style={uiText(12, c.textFaint, { fontWeight: 400 })}> · {s.name}</span>
        </div>
        <div data-testid="stream-control-stream-state" title={state !== shortened(state) ? state : undefined} style={uiText(12, tone, { lineHeight: 1.5, overflowWrap: "anywhere" })}>
          {shortened(state)}
          {s.live && s.viewers !== null ? ` · ${s.viewers} watching` : ""}
        </div>
        {s.chosen && s.live && <StreamBuffer s={s} />}
        {s.chosen && s.live && <StreamHardware hw={s.hardware} />}
        {s.settingsPage && s.enabled && (
          <button
            type="button" data-testid="stream-control-site-settings" onClick={() => openSiteSettings(s)}
            title={`${s.site}'s own settings (its stream key, sign-in and the rest), in a window of its own`}
            style={{ ...headerButton(), marginTop: 4, marginBottom: 2 }}
          >
            <Settings size={13} /> {s.site} settings
          </button>
        )}
        <StreamLinks s={s} />
        {notes.map((n) => (
          <div key={n} style={uiText(12, c.amber, { lineHeight: 1.5 })}>{n}</div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
        {s.hasPage && (
          <button type="button" onClick={() => onOpenPlugin(s.id)} style={headerButton()} title={`Open ${s.name}'s own page`}>
            Open
          </button>
        )}
        {!s.chosen ? null : s.live ? (
          <button
            type="button" data-testid="stream-control-stop" onClick={() => onStop(s.id)} disabled={!!busy || !s.enabled}
            style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}
          >
            {mine ? "Stopping…" : "Stop"}
          </button>
        ) : (
          <button
            type="button" data-testid="stream-control-start" onClick={() => onStart(s.id)} disabled={!!busy || !s.enabled || s.reachable === false}
            style={{ ...headerButton(), color: c.amber, borderColor: c.amber }}
          >
            {mine ? "Going live…" : "Go live"}
          </button>
        )}
      </div>
    </div>
  );
}

// The links the stream's own page shows (YouTube: Watch, and Chat and analytics in YouTube Studio, while there's a
// broadcast; Twitch: Watch, Chat, Stream Manager, Analytics), each opening in a new tab. Just Watch when that's all it says.
function StreamLinks({ s }) {
  const links = s.links.length ? s.links : s.live && s.watchUrl ? [{ label: "Watch", url: s.watchUrl, title: "" }] : [];
  if (!links.length) return null;
  return (
    <div data-testid="stream-control-links" style={uiText(12, c.textMuted, { lineHeight: 1.6, display: "flex", flexWrap: "wrap", gap: "0 10px" })}>
      {links.map((l) => (
        <a key={l.label + l.url} href={l.url} target="_blank" rel="noreferrer" title={l.title || undefined} style={{ color: c.amber }}>{l.label}</a>
      ))}
    </div>
  );
}

// The cameras of the streams going out, once: every stream brought in sends the same design, so they're the same
// cameras. Each in the order the first live stream gives them; one down (or starting) in any stream shows so.
const WORST = { down: 2, starting: 1, live: 0 };
const camerasOf = (streams) => {
  const out = new Map();
  for (const s of streams.filter((x) => x.live && x.chosen)) {
    for (const cam of s.cameras) {
      const key = cam.key || cam.label;
      const had = out.get(key);
      if (!had || WORST[cam.state] > WORST[had.state]) out.set(key, had ? { ...had, state: cam.state } : cam);
    }
  }
  return [...out.values()];
};

// Each camera in the stream while it's live, as the plugin sends it: live, down (its square shows "Camera down"), or
// starting (as a list in two columns, each line the printer's name, then live, down or starting); nothing while none is live
const CAMERA_TONE = { live: "green", down: "danger", starting: "amber" };
function CameraStates({ cameras }) {
  if (!cameras.length) return null;
  const down = cameras.filter((x) => x.state === "down").length;
  return (
    <div data-testid="stream-control-cameras" style={uiText(12, c.textMuted, { lineHeight: 1.6, paddingTop: 8, borderTop: `1px solid ${c.border}` })}>
      <div style={{ color: down ? c.danger : c.textFaint }}>
        {down ? `${down} of ${cameras.length} camera${cameras.length === 1 ? "" : "s"} down` : `All ${cameras.length} camera${cameras.length === 1 ? "" : "s"} live`}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", columnGap: 14 }}>
        {cameras.map((x, i) => (
          <div key={x.key || i} data-testid="stream-control-camera" style={{ display: "flex", gap: 6, minWidth: 0 }}>
            <span style={{ color: c.textPrimary, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={x.label}>{x.label}</span>
            <span style={{ color: c[CAMERA_TONE[x.state]], fontWeight: 600, flexShrink: 0 }}>{x.state}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Copy layout: choose a stream, and its own layout (as set on its own page) becomes Stream control's, shown on every
// stream brought in. Asks first, since it replaces the layout here (save one under Saved layouts to keep it).
function CopyLayout({ streams, busy, onCopy, onClose }) {
  const [from, setFrom] = useState(streams[0]?.id || "");
  const [said, setSaid] = useState(null); // { copied, problems } once done
  const chosen = streams.find((s) => s.id === from);
  const copy = async () => {
    const done = await onCopy(from);
    if (done) setSaid(done);
  };
  return (
    <div data-testid="stream-control-copy" style={{ display: "flex", flexDirection: "column", gap: 8, padding: 10, border: `1px solid ${c.amber}`, borderRadius: 4 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span style={uiText(13, c.textPrimary)}>Copy the layout of</span>
        <select
          data-testid="stream-control-copy-from" value={from} onChange={(e) => (setFrom(e.target.value), setSaid(null))}
          style={{ ...fieldBox(), padding: "5px 8px" }}
        >
          {streams.map((s) => <option key={s.id} value={s.id}>{s.site}</option>)}
        </select>
        <span style={uiText(13, c.textPrimary)}>to all the streams</span>
      </div>
      <div style={help}>
        {chosen?.site || "Its"}'s own layout (its grid and squares, words, colours, music choices, holding screen, title and description)
        replaces Stream control's, and every stream brought in shows it. The pictures and slideshows it uses are copied into the stream
        folder; its music tracks aren't. To keep Stream control's layout as it is now, save it under Saved layouts first.
      </div>
      {said && (
        <div data-testid="stream-control-copied" style={uiText(12, said.problems.length ? c.amber : c.green, { lineHeight: 1.5 })}>
          Copied {chosen?.site}'s layout{said.copied.length ? `, and ${said.copied.length} picture${said.copied.length === 1 ? "" : "s"}` : ""}.
          {said.problems.map((p) => <div key={p}>{p}</div>)}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button type="button" onClick={onClose} style={cancelButton(false)}>{said ? "Close" : "Cancel"}</button>
        {!said && (
          <button type="button" data-testid="stream-control-copy-go" onClick={copy} disabled={!!busy || !from} style={primaryButton(!!busy || !from)}>
            {busy === "copy" ? "Copying…" : "Copy layout"}
          </button>
        )}
      </div>
    </div>
  );
}

const when = (iso) => new Date(iso).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });

// The schedule's last start or stop, and how it went
function LastScheduled({ h }) {
  const failed = h.results.filter((r) => r.error);
  return (
    <div data-testid="stream-control-last-scheduled" style={uiText(12, failed.length ? c.amber : c.textFaint, { lineHeight: 1.5 })}>
      The schedule {h.action === "start" ? "went live" : "stopped"} at {when(h.at)}
      {h.results.length ? `: ${h.results.map((r) => r.name).join(", ")}` : ": no stream plugin to tell"}.
      {failed.map((r) => (
        <div key={r.name}>{r.name}: {r.error}</div>
      ))}
    </div>
  );
}
