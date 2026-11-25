import { useEffect, useRef, useState } from "react";
import { c } from "../theme.js";
import { primaryButton, uiText } from "../styles.js";
import { errorText, getStreamClips, setStreamClipLength, streamClipUrl, takeStreamClip, timeZone } from "../api.js";
import { box, heading, help, label12, panel } from "./streamStyles.js";

// Clips of Stream control's stream: every stream brought in sends the same picture, so the clip is taken by one of their
// plugins, chosen here (clipper): one that takes clips first (not one from before Stream control, nor one that said it
// doesn't); of those, a live one (the one holding the most of its delay, so the most footage), else the first one
// brought in. Once chosen it stays chosen while it's still live (or none is), so it doesn't flip while their delays fill. A small line says which, and where it keeps them (each plugin saves MP4s in its own clips
// folder). Clip: the stream (the last stretch of what went out, saved at once) or any camera Farmhand can see (the next
// stretch from it, recorded by that plugin in the background: the panel says while it is, and how it ended). The length
// (1 s to 5 min) is that plugin's, typed here. `streams`: as getStreamPlugins gives them.
const STREAM = "stream";
const clipper = (streams, before, noClips) => {
  const usable = streams.filter((s) => s.enabled && s.chosen);
  const takes = usable.filter((s) => !s.needsUpdate && !noClips.includes(s.id));
  const pool = takes.length ? takes : usable;
  const live = pool.filter((s) => s.live);
  const kept = pool.find((s) => s.id === before);
  if (kept && (kept.live || !live.length)) return kept;
  return [...live].sort((a, b) => (b.buffer?.held ?? 0) - (a.buffer?.held ?? 0))[0] || pool[0] || null;
};
// (the words Farmhand answers with for a stream plugin that doesn't take clips)
const NO_CLIPS = "doesn't take clips";
const size = (bytes) => (bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} kB`);
const length = (s) => (s < 60 ? `${s} s` : s % 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s / 60} min`);
// "45", "90 s", "2:30", "3 min" -> seconds; null when it isn't a length
const parseLength = (text) => {
  const t = String(text).trim().toLowerCase();
  let m = t.match(/^(\d+):([0-5]\d)$/);
  if (m) return Number(m[1]) * 60 + Number(m[2]);
  m = t.match(/^(\d+)\s*(s|sec|secs|seconds?)?$/);
  if (m) return Number(m[1]);
  m = t.match(/^(\d+(?:\.\d+)?)\s*(m|min|mins|minutes?)$/);
  return m ? Math.round(Number(m[1]) * 60) : null;
};

export function ClipsPanel({ streams }) {
  const [noClips, setNoClips] = useState([]); // the plugins that said they don't take clips
  const before = useRef(null);
  const by = clipper(streams, before.current, noClips);
  before.current = by?.id || null;
  const asking = useRef(null); // the plugin chosen now: an answer about another one, come late, is let go
  const [source, setSource] = useState(STREAM);
  const [clips, setClips] = useState(null);
  const [problem, setProblem] = useState(null); // the plugin couldn't be asked
  const [said, setSaid] = useState(null); // { text, tone }: what the last clip did
  const [busy, setBusy] = useState(false);
  const [typed, setTyped] = useState(null); // the length as being typed (null: as the plugin has it)
  const [, tick] = useState(0); // (a recording's seconds left count down)
  const id = by?.id || null;
  asking.current = id;

  const load = (which = id) =>
    which &&
    getStreamClips(which)
      .then((k) => {
        if (which !== asking.current) return;
        setClips(k);
        setProblem(null);
      })
      .catch((e) => {
        if (which !== asking.current) return;
        if (e.status === 422 && errorText(e).includes(NO_CLIPS)) {
          setNoClips((now) => (now.includes(which) ? now : [...now, which])); // (another one that does is chosen, if there is one)
        }
        setClips(null);
        setProblem(errorText(e));
      });
  const recordingNow = (clips?.recording || []).length > 0;
  const liveNow = !!by?.live; // (asked again as it goes live or stops: what it holds changes)
  useEffect(() => {
    if (!id) return undefined;
    load(id);
    const every = setInterval(() => load(id), recordingNow ? 2000 : 15000); // (more often while a camera is being recorded)
    const clock = recordingNow ? setInterval(() => tick((n) => n + 1), 1000) : null;
    return () => {
      clearInterval(every);
      if (clock) clearInterval(clock);
    };
  }, [id, recordingNow, liveNow]);

  const here = clips && clips.plugin === id ? clips : null;
  const site = by?.site || "";
  const where = here ? here.folder.shownAs || here.folder.path : "";
  const folderProblem = here?.folder.problem || null;
  const chosen = here ? here.sources.find((s) => s.key === source) || here.sources[0] : null;
  const isStream = !chosen || chosen.key === STREAM;
  const nothing = !!here && isStream && here.held <= 0;
  const already = !!here && !isStream && here.recording.some((r) => r.source === chosen.key);
  const blocked = busy || !here || !!folderProblem || nothing || already;
  const shown = here?.seconds ?? 0;

  const keepLength = async () => {
    if (typed === null || !here) return;
    const s = parseLength(typed);
    if (s === null || s < here.least || s > here.most) {
      setSaid({ text: `Type ${here.least} second to ${here.most / 60} minutes, e.g. 3, 45, 90 s, 2:30 or 3 min.`, tone: "bad" });
      return;
    }
    const which = id;
    try {
      const got = await setStreamClipLength(which, s);
      if (which !== asking.current) return;
      setClips(got);
      setTyped(null);
      setSaid(null);
    } catch (e) {
      if (which === asking.current) setSaid({ text: errorText(e), tone: "bad" });
    }
  };
  const take = async () => {
    const which = id;
    setBusy(true);
    setSaid(null);
    try {
      const got = await takeStreamClip(which, chosen.key, timeZone);
      if (which !== asking.current) return;
      if (got.clips) setClips(got.clips);
      else load(which); // (taken, but the plugin didn't then say its clips: asked again)
      if (got.saved) setSaid({ text: `Saved “${got.saved.name}” (${size(got.saved.size)}) in ${where}.`, tone: "good" });
    } catch (e) {
      if (which === asking.current) setSaid({ text: errorText(e), tone: "bad" });
    } finally {
      setBusy(false);
    }
  };
  const left = (r) => Math.max(0, Math.ceil((r.until - Date.now()) / 1000));

  return (
    <div data-testid="stream-control-clips" style={panel()}>
      <div style={heading}>Clips</div>
      {!by ? (
        <div style={help}>Bring a stream in under Streams to take clips of it.</div>
      ) : (
        <>
          <div style={help}>
            Save a clip as a video file: the last stretch of the stream as it went out, or the next stretch from any camera.
          </div>
          <div data-testid="stream-control-clip-by" style={uiText(12, c.textFaint, { lineHeight: 1.5 })}>
            Saved by the {site} plugin{where ? <>, in <span style={{ color: c.textPrimary }}>{where}</span></> : ""}
            {by.live ? "" : " (no stream is live)"}.
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {here && (
              <label style={label12}>
                Clip
                <select
                  data-testid="stream-control-clip-source" value={chosen.key}
                  onChange={(e) => (setSource(e.target.value), setSaid(null))} style={{ ...box(), maxWidth: 240 }}
                >
                  {here.sources.map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {problem && <div data-testid="stream-control-clips-problem" style={uiText(12, c.danger, { lineHeight: 1.5 })}>{problem}</div>}
          {here && (
            <>
              <label style={{ ...label12, flexWrap: "wrap" }}>
                Length
                <input
                  data-testid="stream-control-clip-length" value={typed ?? String(shown)} onChange={(e) => setTyped(e.target.value)}
                  onBlur={keepLength} onKeyDown={(e) => e.key === "Enter" && keepLength()}
                  aria-label="How long a clip is, in seconds" style={{ ...box(), width: 70 }}
                />
                <span style={uiText(12, c.textFaint)}>
                  seconds{typed === null && shown >= 60 ? ` (${length(shown)})` : ""} · {here.least} s to {here.most / 60} min
                </span>
              </label>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  type="button" data-testid="stream-control-clip-save" onClick={take} disabled={blocked} style={primaryButton(blocked)}
                  title={folderProblem || (nothing ? `Go live first: a clip of the stream is taken from what has gone to ${site}`
                    : already ? `${chosen.label} is being recorded already`
                    : isStream ? `Save the last ${length(shown)} that went to ${site}` : `Record the next ${length(shown)} from ${chosen.label}`)}
                >
                  {busy ? (isStream ? "Saving the clip…" : "Starting…") : isStream ? `Save clip (last ${length(shown)})` : `Record clip (next ${length(shown)})`}
                </button>
                {!folderProblem && nothing && <span style={uiText(12, c.textFaint)}>Nothing has gone to {site} yet.</span>}
                {!folderProblem && isStream && !nothing && here.held < shown && (
                  <span style={uiText(12, c.textFaint)}>Only {length(Math.floor(here.held))} has gone out so far: the clip is that long.</span>
                )}
              </div>
              {folderProblem && <div style={uiText(12, c.amber, { lineHeight: 1.5 })}>{folderProblem}</div>}
              {here.recording.map((r) => (
                <div key={r.source} data-testid="stream-control-clip-recording" style={uiText(12, c.amber, { lineHeight: 1.5 })}>
                  Recording {r.label}: {left(r) > 0 ? `${length(left(r))} to go` : "finishing…"}
                </div>
              ))}
              {here.ended.slice(0, 1).map((r) => (
                <div key={`${r.source}-${r.name || r.text}`} style={uiText(12, r.ok ? c.green : c.danger, { lineHeight: 1.5 })}>
                  {r.label}: {r.text}
                </div>
              ))}
            </>
          )}
          {said && (
            <div data-testid="stream-control-clip-said" style={uiText(12, said.tone === "bad" ? c.danger : c.green, { lineHeight: 1.5 })}>{said.text}</div>
          )}
          {here && here.clips.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <div style={uiText(11, c.textFaint)}>Latest clips</div>
              {here.clips.map((x) => (
                <a key={x.name} href={streamClipUrl(id, x.name)} download={x.name} data-testid="stream-control-clip" style={uiText(12, c.fileName, { textDecoration: "none" })}>
                  {x.name} <span style={{ color: c.textFaint }}>· {size(x.size)}</span>
                </a>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
