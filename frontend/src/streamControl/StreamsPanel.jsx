import { Radio } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, headerButton, primaryButton, uiText } from "../styles.js";
import { heading, help, panel } from "./streamStyles.js";

// The stream plugins (YouTube, Twitch...) that send the stream designed here, each with how its stream is doing and
// its own Start and Stop, and Start all / Stop all. A plugin is one when its manifest says it can be started from here
// (docs/plugins.md, stream_control). `streams`: as getStreamPlugins gives them; `busy`: what's being asked ("start:stream",
// "stop-all"...); `onStart(id)`, `onStop(id)`, `onAll("start" | "stop")`; `onOpenPlugin(id)` opens its own page;
// `onOpenPlugins` the Plugins page; `happened`: what the schedule did lately. Each has a tick box: which ones Stream
// control brings in (`onChoose(ids)`). One left out keeps its own layout, and isn't started or stopped from here.
export function StreamsPanel({ streams, busy, onStart, onStop, onAll, onChoose, onOpenPlugin, onOpenPlugins, happened = [] }) {
  const usable = streams.filter((s) => s.enabled && s.chosen);
  const toggle = (id) => onChoose(streams.filter((s) => (s.id === id ? !s.chosen : s.chosen)).map((s) => s.id));
  const anyLive = usable.some((s) => s.live);
  const allLive = usable.length > 0 && usable.every((s) => s.live);
  return (
    <div data-testid="stream-control-streams" style={panel()}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ ...heading, flex: 1 }}>Streams</div>
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
      {!streams.length && (
        <div style={help}>
          No stream plugin is added yet. Add the YouTube or Twitch stream plugin on the{" "}
          <button type="button" onClick={onOpenPlugins} style={{ ...uiText(12, c.amber), background: "none", border: "none", padding: 0, textDecoration: "underline", cursor: "pointer" }}>
            Plugins page
          </button>
          , and it shows here to start and stop.
        </div>
      )}
      {streams.length > 0 && (
        <div style={help}>Tick the streams Stream control brings in: they send this stream, and go live and stop from here.</div>
      )}
      {streams.map((s) => (
        <StreamRow key={s.id} s={s} busy={busy} onStart={onStart} onStop={onStop} onToggle={() => toggle(s.id)} onOpenPlugin={onOpenPlugin} />
      ))}
      {happened.length > 0 && <LastScheduled h={happened[0]} />}
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
        <div data-testid="stream-control-stream-state" style={uiText(12, tone, { lineHeight: 1.5 })}>
          {state}
          {s.live && s.watchUrl && (
            <>
              {" · "}
              <a href={s.watchUrl} target="_blank" rel="noreferrer" style={{ color: c.amber }}>Watch</a>
            </>
          )}
        </div>
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
