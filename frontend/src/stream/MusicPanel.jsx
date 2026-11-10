import { useEffect, useRef, useState } from "react";
import { Music, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { c } from "../theme.js";
import { headerButton, linkButton, uiText } from "../styles.js";
import { musicControl, removeStreamTrack, scanStreamFolder, streamTrackUrl, uploadStreamMusic } from "../api.js";
import { heading, help, label12, panel } from "./streamStyles.js";
import { OpenFolder } from "./MediaChoices.jsx";

// The stream's music: MP3s in the stream folder's music folder (StreamBeats, say), played one after another and round
// again (shuffled each round, if chosen), in place of the silent sound track, starting with the stream. On or off, its
// volume and shuffling are saved with the page's Save (and followed straight away while live); tracks are uploaded and
// deleted straight away. Back, Play/Pause and Next, beside "Play music on the stream": while live, the music going out
// (the server's music player); not live, the tracks played here in this browser, at the volume chosen, to hear how they
// sound (each track's own ▶ too). `shown`/`change`: the page's choices; `media`: the stream folder (media.music: the
// tracks' file names); `ask`, `busy`: the page's own way of asking the server; `live`: the stream is meant to be going
// out; `onAir`: the music going out (status.music: { on, playing, track, at }) and `heardAt`, when that was heard.

// the volume as the server plays it: the slider squared, so its middle sounds about half as loud
export const musicGain = (volume) => (Math.max(0, Math.min(100, Number(volume) || 0)) / 100) ** 2;
const BACK_RESTARTS = 3; // seconds into a track after which Back starts it again, as on the stream
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const small = { ...headerButton(), padding: "0 6px" };

export function MusicPanel({ shown, change, media, ask, busy, live, onAir = null, heardAt = 0, enabled = true, control = null, onWaiting = null, muted = false }) {
  const input = useRef(null);
  const player = useRef(null);
  const paused = useRef(false); // paused here by hand: it stays so until played again (or the switch turned on again)
  const latest = useRef({}); // (what a track ending goes on with: the list and shuffling as they are now)
  const requests = useRef(0); // (each track asked for: only the latest's answer counts)
  const [here, setHere] = useState(null); // the track played here: { name, paused, waiting (for a click: the browser's rule) }
  const [removing, setRemoving] = useState(null); // the track asking "Delete?"
  const [opening, setOpening] = useState(false); // showing where the music folder is, for File Explorer
  const [, tick] = useState(0); // (live: the time into the track goes on between the page's looks)
  const tracks = media.music || [];
  const off = !!busy || !!media.error;
  const playing = here && !here.paused ? here.name : null;
  // the browser holding the music back until the page is clicked: the page says so by the switch, where it's seen
  useEffect(() => onWaiting?.(!!here?.waiting), [!!here?.waiting]);

  const stopHere = () => {
    player.current?.pause();
    setHere(null);
  };
  useEffect(() => {
    if (player.current) {
      player.current.volume = musicGain(shown.musicVolume);
      player.current.muted = muted;
    }
  }, [shown.musicVolume, here, muted]);
  useEffect(() => {
    if (here && !tracks.includes(here.name)) stopHere(); // deleted, or gone from the folder
  }, [tracks, here]);
  useEffect(() => () => player.current?.pause(), []);
  useEffect(() => {
    if (!live || !onAir?.playing) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [live, onAir?.playing]);
  // Live, the page plays along with the stream: the track the server is sending, from where it is, paused when it is
  // (each look at the server brings it back in step), so you hear what viewers hear. Mute (beside the switch) silences
  // it here only.
  useEffect(() => {
    if (!live) return;
    if (!enabled || !onAir?.on || !onAir.track) {
      stopHere();
      return;
    }
    const at = onAir.at + (onAir.playing ? Math.max(0, (Date.now() - heardAt) / 1000) : 0);
    if (here?.name !== onAir.track) {
      playHere(onAir.track, at, onAir.playing);
      return;
    }
    const a = player.current;
    if (!a || here.waiting) return;
    if (!onAir.playing) {
      a.pause();
      if (!here.paused) setHere({ name: here.name, paused: true });
      return;
    }
    if (Math.abs(a.currentTime - at) > 2) a.currentTime = at; // drifted: back in step
    if (here.paused) {
      a.play().catch(() => {});
      setHere({ name: here.name, paused: false });
    }
  }, [live, enabled, onAir?.on, onAir?.track, onAir?.playing, heardAt]);
  // With the stream on, the music plays here all the time, as the slideshows do (live, the stream plays it instead):
  // round and round, as on the stream. The switch off, or the music unticked, stops it.
  const wanted = enabled && !live && shown.music && tracks.length > 0;
  useEffect(() => {
    if (!enabled) paused.current = false; // (turned on again: it starts again)
    if (!wanted) {
      if (!live) stopHere();
      return;
    }
    if (!here && !paused.current) advance(null, 1);
  }, [wanted, enabled]);
  latest.current = { tracks, shuffle: shown.musicShuffle, live };
  // the switch's own: start (turned on, from within its click) and stop (it couldn't be turned on)
  if (control) {
    control.current = {
      start: () => {
        paused.current = false;
        if (!live && shown.music && tracks.length && !here) advance(null, 1);
      },
      stop: () => stopHere(),
    };
  }

  // the track `step` along from `name` in the list (round again at either end; shuffled, going on: any other one),
  // played here
  const advance = (name, step) => {
    const { tracks: list, shuffle } = latest.current;
    if (!list.length) return;
    const i = list.indexOf(name);
    if (shuffle && step > 0 && list.length > 1) {
      const others = list.filter((x) => x !== name);
      return playHere(others[Math.floor(Math.random() * others.length)]);
    }
    return playHere(list[(((i < 0 ? 0 : i + step) % list.length) + list.length) % list.length]);
  };
  // `at`: from that far in (playing along with the stream); `go`: false, loaded but held paused
  const playHere = (name, at = 0, go = true) => {
    const a = player.current || (player.current = new Audio());
    a.onended = () => !latest.current.live && advance(name, 1); // on to the next, as the stream does (live: as it says)
    a.onloadedmetadata = at ? () => (a.currentTime = Math.min(at, a.duration || at)) : null;
    a.src = streamTrackUrl(name);
    a.volume = musicGain(shown.musicVolume);
    a.muted = muted;
    paused.current = false;
    const asked = ++requests.current;
    if (!go) return setHere({ name, paused: true });
    setHere({ name, paused: false });
    return a.play().catch((e) => {
      if (asked !== requests.current) return undefined; // another track asked for since: it's that one's
      if (e?.name !== "NotAllowedError") return setHere(null);
      // the browser plays sound only once the page has been clicked: it starts with the first click or key
      setHere({ name, paused: true, waiting: true });
      const go = () => {
        document.removeEventListener("pointerdown", go, true);
        document.removeEventListener("keydown", go, true);
        if (player.current === a && !paused.current) {
          a.play().then(() => setHere({ name, paused: false })).catch(() => setHere(null));
        }
      };
      document.addEventListener("pointerdown", go, true);
      document.addEventListener("keydown", go, true);
      return undefined;
    });
  };
  const pauseHere = () => {
    player.current?.pause();
    paused.current = true;
    setHere((h) => h && { name: h.name, paused: true });
  };
  // each track's own ▶: play it here, or pause it
  const toggleTrack = (name) => (playing === name ? pauseHere() : playHere(name));

  // Back, Play/Pause, Next: the stream's music while live, otherwise here
  const server = (action) => ask("music", () => musicControl(action));
  const isPlaying = live ? !!onAir?.playing : !!playing || !!here?.waiting; // (waiting for a click: going, as far as you're concerned)
  const back = () => {
    if (live) return server("back");
    if (!here) return advance(tracks[0], 0);
    if ((player.current?.currentTime || 0) > BACK_RESTARTS) return playHere(here.name);
    return advance(here.name, -1);
  };
  const next = () => (live ? server("next") : advance(here ? here.name : tracks[0], here ? 1 : 0));
  const playPause = () => {
    if (live) return server(onAir?.playing ? "pause" : "play");
    if (!here) return advance(tracks[0], 0);
    if (playing) return pauseHere();
    paused.current = false;
    player.current.play().catch(() => setHere(null));
    return setHere({ name: here.name, paused: false });
  };
  const liveOff = live && !onAir?.on; // live with the music off (as saved): nothing to control
  const controlsOff = !!busy || liveOff || (!live && !tracks.length);
  const at = onAir ? onAir.at + (onAir.playing ? Math.max(0, (Date.now() - heardAt) / 1000) : 0) : 0;
  let nowText = "";
  if (live && !onAir?.on) nowText = "The music is off on the stream (tick Play music on the stream and Save)";
  else if (live && onAir.track) nowText = `On the stream: ${onAir.track} · ${clock(at)}${onAir.playing ? "" : " (paused)"}`;
  else if (live) nowText = tracks.length ? "On the stream: starting…" : "On the stream: no tracks, so silence";
  else if (here?.waiting) nowText = `Here: ${here.name} · starts with your first click on the page (the browser waits for one)`;
  else if (here) nowText = `Here: ${here.name}${here.paused ? " (paused)" : ""}`;
  else if (tracks.length) nowText = "Not live: the buttons play the tracks here, in this browser";

  const upload = async (files) => {
    if (files.length) await ask("music", () => uploadStreamMusic(files));
    input.current.value = "";
  };
  const remove = async (name) => {
    if (here?.name === name) stopHere();
    if (await ask("music", () => removeStreamTrack(name))) setRemoving(null);
  };

  return (
    <div data-testid="stream-music-panel" style={panel()}>
      <div style={{ ...heading, display: "flex", alignItems: "center", gap: 6 }}>
        <Music size={15} /> Music
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <label style={label12}>
          <input type="checkbox" data-testid="stream-music-on" checked={shown.music} onChange={(e) => change({ music: e.target.checked })} />
          Play music on the stream
        </label>
        <div style={{ display: "flex", gap: 4 }}>
          <button
            type="button" data-testid="stream-music-back" onClick={back} disabled={controlsOff} style={small} aria-label="Back"
            title={live ? "Back, on the stream: this track from its start (in its first seconds, the one before)" : "Back (here)"}
          >
            <SkipBack size={13} />
          </button>
          <button
            type="button" data-testid="stream-music-play" onClick={playPause} disabled={controlsOff} style={small} aria-label={isPlaying ? "Pause" : "Play"}
            title={live ? (isPlaying ? "Pause the stream's music (silence until Play)" : "Play the stream's music") : isPlaying ? "Pause (here)" : "Play (here)"}
          >
            {isPlaying ? <Pause size={13} /> : <Play size={13} />}
          </button>
          <button
            type="button" data-testid="stream-music-next" onClick={next} disabled={controlsOff} style={small} aria-label="Next"
            title={live ? "Next track, on the stream" : "Next track (here)"}
          >
            <SkipForward size={13} />
          </button>
        </div>
      </div>
      {nowText && (
        <div data-testid="stream-music-now" style={uiText(12, live && onAir?.track ? c.heading : c.textMuted, { marginTop: -4 })}>
          {nowText}
        </div>
      )}
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", opacity: shown.music ? 1 : 0.6 }}>
        <label style={label12}>
          Volume
          <input
            type="range" data-testid="stream-music-volume" min={0} max={100} step={1} value={shown.musicVolume}
            onChange={(e) => change({ musicVolume: Number(e.target.value) })} style={{ width: 140 }}
          />
          <span style={{ minWidth: 34 }}>{shown.musicVolume}%</span>
        </label>
        <label style={label12}>
          <input type="checkbox" data-testid="stream-music-shuffle" checked={shown.musicShuffle} onChange={(e) => change({ musicShuffle: e.target.checked })} />
          Shuffle
        </label>
      </div>

      <div data-testid="stream-music-tracks" style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 220, overflowY: "auto" }}>
        {!tracks.length && <div style={uiText(12, c.textFaint)}>{media.error ? `The stream folder can't be used now: ${media.error}` : "No tracks yet."}</div>}
        {tracks.map((name) => (
          <div key={name} data-testid="stream-music-track" style={{ display: "flex", alignItems: "center", gap: 6, minHeight: 26 }}>
            <button
              type="button" onClick={() => toggleTrack(name)} title={playing === name ? "Pause" : "Play it here, in this browser, at the volume chosen"}
              aria-label={playing === name ? `Pause ${name}` : `Play ${name}`} style={small}
            >
              {playing === name ? <Pause size={13} /> : <Play size={13} />}
            </button>
            <span style={uiText(12, here?.name === name || (live && onAir?.track === name) ? c.heading : c.textMuted, { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })} title={name}>
              {name}
            </span>
            {removing === name ? (
              <>
                <button type="button" onClick={() => remove(name)} disabled={!!busy} style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}>
                  Delete
                </button>
                <button type="button" onClick={() => setRemoving(null)} style={headerButton()}>
                  Keep
                </button>
              </>
            ) : (
              <button type="button" data-testid="stream-music-delete" onClick={() => setRemoving(name)} disabled={!!busy} style={headerButton()}>
                Delete
              </button>
            )}
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input ref={input} data-testid="stream-music-file" type="file" multiple accept=".mp3,audio/mpeg" style={{ display: "none" }} onChange={(e) => upload([...e.target.files])} />
        <button type="button" data-testid="stream-music-upload" onClick={() => input.current.click()} disabled={off} style={headerButton()}>
          {busy === "music" ? "Working…" : "Add tracks"}
        </button>
        <button
          type="button" onClick={() => ask("music", scanStreamFolder)} disabled={!!busy} style={headerButton()}
          title="Look in the stream folder again, for tracks copied in or taken out by hand"
        >
          Scan folder
        </button>
        <button
          type="button" data-testid="stream-music-open-folder" onClick={() => setOpening(!opening)} style={{ ...headerButton(), color: opening ? c.amber : c.textMuted }}
          title="Where the music folder is, to open in File Explorer"
        >
          Open folder
        </button>
        <span style={uiText(11, c.textFaint)}>{tracks.length ? `${tracks.length} track${tracks.length === 1 ? "" : "s"}` : ""}</span>
      </div>
      {opening && <OpenFolder media={media} rest="music" what="Tracks" testid="stream-music" />}
      <div style={help}>
        MP3s, played one after another and round again{shown.musicShuffle ? ", in a new order each round" : ", in name order"}. Free music
        for streams, such as{" "}
        <a href="https://www.streambeats.com/" target="_blank" rel="noreferrer" style={linkButton(12)}>
          StreamBeats
        </a>
        , can be downloaded and added here (under 50 MB each), or copied into the stream folder's music folder (Open folder) and found with Scan folder.
        {shown.music && !tracks.length ? " With no tracks, the stream stays silent." : ""}
        {" "}The music starts with the stream{live ? "; tracks added while live join its next round" : ""}.
      </div>
    </div>
  );
}
