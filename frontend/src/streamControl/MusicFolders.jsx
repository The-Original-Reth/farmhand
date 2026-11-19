import { useState } from "react";
import { c } from "../theme.js";
import { uiText } from "../styles.js";
import { help, label12 } from "./streamStyles.js";

// Which music folders the stream plays: Stream control's own, YouTube's own, Twitch's own, any or all of them at once.
// Nothing is copied: a stream plugin's tracks are played from its own folder. Saved straight away (`onChoose(ids)`),
// so the tracks below are the ones that play. `sources`: [{ id, label, chosen, tracks, problem }].
export function MusicFolders({ sources, chosen, busy, onChoose }) {
  const [note, setNote] = useState(null);
  if (sources.length < 2) return null; // (only Stream control's own: nothing to choose)
  // Each folder is ticked on its own. One stays ticked (music off is the Music switch above): unticking the last one
  // says so instead of greying it out.
  const toggle = (id) => {
    const next = chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id];
    if (!next.length) return setNote("Keep at least one music folder ticked. To play no music, turn Music off.");
    setNote(null);
    onChoose(sources.map((s) => s.id).filter((x) => next.includes(x)));
  };
  return (
    <div data-testid="stream-control-music-folders" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={label12}>Play the music in</span>
        {sources.map((s) => (
          <label key={s.id} style={label12} title={s.problem || undefined}>
            <input
              type="checkbox" data-testid="stream-control-music-folder" checked={chosen.includes(s.id)} disabled={!!busy}
              onChange={() => toggle(s.id)}
            />
            {s.label}
            <span style={uiText(11, s.problem ? c.amber : c.textFaint)}>({s.problem ? (s.tracks ? `${s.tracks} track${s.tracks === 1 ? "" : "s"}, not answering just now` : "not answering") : `${s.tracks} track${s.tracks === 1 ? "" : "s"}`})</span>
          </label>
        ))}
      </div>
      {note && <div role="status" style={uiText(12, c.amber)}>{note}</div>}
      <div style={help}>
        Tick one folder or several: their tracks all play, one after another. A stream's own music is played from its own folder, never copied.
      </div>
    </div>
  );
}
