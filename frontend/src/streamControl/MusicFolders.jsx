import { c } from "../theme.js";
import { uiText } from "../styles.js";
import { help, label12 } from "./streamStyles.js";

// Which music folders the stream plays: Stream control's own, YouTube's own, Twitch's own, any or all of them at once.
// Nothing is copied: a stream plugin's tracks are played from its own folder. Saved straight away (`onChoose(ids)`),
// so the tracks below are the ones that play. `sources`: [{ id, label, chosen, tracks, problem }].
export function MusicFolders({ sources, chosen, busy, onChoose }) {
  if (sources.length < 2) return null; // (only Stream control's own: nothing to choose)
  const toggle = (id) => {
    const next = chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id];
    if (next.length) onChoose(sources.map((s) => s.id).filter((x) => next.includes(x)));
  };
  return (
    <div data-testid="stream-control-music-folders" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={label12}>Play the music in</span>
        {sources.map((s) => (
          <label key={s.id} style={label12} title={s.problem || undefined}>
            <input
              type="checkbox" data-testid="stream-control-music-folder" checked={chosen.includes(s.id)} disabled={!!busy || (chosen.length === 1 && chosen.includes(s.id))}
              onChange={() => toggle(s.id)}
            />
            {s.label}
            <span style={uiText(11, s.problem ? c.amber : c.textFaint)}>({s.problem ? "not answering" : `${s.tracks} track${s.tracks === 1 ? "" : "s"}`})</span>
          </label>
        ))}
      </div>
      <div style={help}>
        Tick one folder or several: their tracks all play, one after another. A stream's own music is played from its own folder, never copied.
      </div>
    </div>
  );
}
