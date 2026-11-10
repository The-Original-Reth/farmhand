import { useEffect, useRef, useState } from "react";
import { Music, Pause, Play } from "lucide-react";
import { c } from "../theme.js";
import { headerButton, linkButton, uiText } from "../styles.js";
import { removeStreamTrack, scanStreamFolder, streamTrackUrl, uploadStreamMusic } from "../api.js";
import { heading, help, label12, panel } from "./streamStyles.js";
import { OpenFolder } from "./MediaChoices.jsx";

// The stream's music: MP3s in the stream folder's music folder (StreamBeats, say), played one after another and round
// again (shuffled each round, if chosen), in place of the silent sound track. On or off, its volume and shuffling are saved with the page's Save; tracks
// are uploaded and deleted straight away. Each track can be played here, at the volume chosen, to hear how it sounds.
// `shown`/`change`: the page's choices; `media`: the stream folder (media.music: the tracks' file names); `ask`, `busy`:
// the page's own way of asking the server; `live`: the stream is meant to be going out.

// the volume as the server plays it: the slider squared, so its middle sounds about half as loud
export const musicGain = (volume) => (Math.max(0, Math.min(100, Number(volume) || 0)) / 100) ** 2;

export function MusicPanel({ shown, change, media, ask, busy, live }) {
  const input = useRef(null);
  const player = useRef(null);
  const [playing, setPlaying] = useState(null); // the track playing here
  const [removing, setRemoving] = useState(null); // the track asking "Delete?"
  const [opening, setOpening] = useState(false); // showing where the music folder is, for File Explorer
  const tracks = media.music || [];
  const off = !!busy || !!media.error;

  useEffect(() => {
    if (player.current) player.current.volume = musicGain(shown.musicVolume);
  }, [shown.musicVolume, playing]);
  useEffect(() => {
    if (playing && !tracks.includes(playing)) setPlaying(null); // deleted, or gone from the folder
  }, [tracks, playing]);
  useEffect(() => () => player.current?.pause(), []);

  const play = (name) => {
    if (playing === name) {
      player.current.pause();
      setPlaying(null);
      return;
    }
    const a = player.current || (player.current = new Audio());
    a.onended = () => setPlaying(null);
    a.src = streamTrackUrl(name);
    a.volume = musicGain(shown.musicVolume);
    a.play().catch(() => setPlaying(null));
    setPlaying(name);
  };
  const upload = async (files) => {
    if (files.length) await ask("music", () => uploadStreamMusic(files));
    input.current.value = "";
  };
  const remove = async (name) => {
    if (playing === name) play(name);
    if (await ask("music", () => removeStreamTrack(name))) setRemoving(null);
  };

  return (
    <div data-testid="stream-music-panel" style={panel()}>
      <div style={{ ...heading, display: "flex", alignItems: "center", gap: 6 }}>
        <Music size={15} /> Music
      </div>
      <label style={label12}>
        <input type="checkbox" data-testid="stream-music-on" checked={shown.music} onChange={(e) => change({ music: e.target.checked })} />
        Play music on the stream
      </label>
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", opacity: shown.music ? 1 : 0.6 }}>
        <label style={label12}>
          Volume
          <input
            type="range" data-testid="stream-music-volume" min={0} max={100} step={5} value={shown.musicVolume}
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
              type="button" onClick={() => play(name)} title={playing === name ? "Stop" : "Play it here, at the volume chosen"}
              aria-label={playing === name ? `Stop ${name}` : `Play ${name}`} style={{ ...headerButton(), padding: "0 6px" }}
            >
              {playing === name ? <Pause size={13} /> : <Play size={13} />}
            </button>
            <span style={uiText(12, playing === name ? c.heading : c.textMuted, { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })} title={name}>
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
        {live ? " Tracks added or deleted while live play from the next time the stream starts." : ""}
      </div>
    </div>
  );
}
