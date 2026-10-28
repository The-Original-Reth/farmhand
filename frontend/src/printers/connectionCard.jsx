import { useRef, useState } from "react";
import { c, fs, ui } from "../theme.js";
import { monoText } from "../styles.js";

// What the Moonraker and PrusaLink cards share: how a printer's live status is held, its connection line, and the
// count of prints Farmhand has on record.

// The printer's status as last looked at. Setting it to an answer the same as the last redraws nothing (the page looks
// every few seconds, and most answers haven't changed).
export function useLiveStatus() {
  const [status, setStatusNow] = useState(null);
  const seen = useRef("");
  const setStatus = (s) => {
    const json = JSON.stringify(s);
    if (json !== seen.current) setStatusNow(s);
    seen.current = json;
  };
  return [status, setStatus];
}

// A coloured dot and a line saying how the printer is ("Connected · Klipper ready"), with its address while it answers
export function ConnectionLine({ testId, dot, line, reachable, url }) {
  return (
    <div data-testid={testId} style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: reachable ? c.textPrimary : c.textMuted, lineHeight: 1.5 }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: dot, flexShrink: 0, marginTop: 6 }} />
      <span>
        {line}
        {reachable && url && <span style={monoText(11, c.textFaint, { marginLeft: 8 })}>{url}</span>}
      </span>
    </div>
  );
}

// "Farmhand has 12 prints on record: 9 completed, 1 cancelled, 2 failed." (nothing while there are none).
// archive: the print-stats answer's { jobs, by_status }. failedLabel: what the rest are called.
export function ArchiveSummary({ archive, failedLabel }) {
  if (!(archive?.jobs > 0)) return null;
  const { by_status: by } = archive;
  const failed = archive.jobs - (by.completed || 0) - (by.in_progress || 0) - (by.cancelled || 0);
  return (
    <div>
      Farmhand has {archive.jobs.toLocaleString()} print{archive.jobs === 1 ? "" : "s"} on record:{" "}
      {(by.completed || 0).toLocaleString()} completed, {(by.cancelled || 0).toLocaleString()} cancelled,{" "}
      {failed.toLocaleString()} {failedLabel}{by.in_progress ? `, ${by.in_progress} in progress` : ""}.
    </div>
  );
}
