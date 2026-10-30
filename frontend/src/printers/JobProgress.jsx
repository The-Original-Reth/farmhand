import { c } from "../theme.js";
import { monoText, uiText } from "../styles.js";

import { ProgressBar } from "../components/common/ui.jsx";
import { fmtDuration } from "../lib/format.js";

// The print a printer is running: its file, a progress bar (amber while paused) and
// "42% · 1h 3m printed · 1h 27m left · paused". Shared by the PrusaLink and Moonraker cards.
// note: a state worth saying after the times ("paused", "finished"), or nothing while it's simply printing
export function JobProgress({ testId, file, progress, printed, left, paused, note }) {
  return (
    <div data-testid={testId} style={{ marginTop: 12 }}>
      <div style={uiText(13, c.heading, { fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })} title={file}>
        {file || "Printing"}
      </div>
      <ProgressBar pct={progress} color={paused ? c.amber : c.teal} style={{ marginTop: 6 }} />
      <div style={monoText(11, c.textFaint, { marginTop: 4 })}>
        {Math.round(progress || 0)}% · {fmtDuration(printed || 0)} printed
        {left != null ? ` · ${fmtDuration(left)} left` : ""}
        {note ? ` · ${note}` : ""}
      </div>
    </div>
  );
}
