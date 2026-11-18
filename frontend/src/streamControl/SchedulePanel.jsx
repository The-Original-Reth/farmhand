import { useEffect, useState } from "react";
import { CalendarClock, Trash2 } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, headerButton, primaryButton, uiText } from "../styles.js";
import { errorText, saveStreamSchedule } from "../api.js";
import { box, heading, help, label12, panel } from "./streamStyles.js";

// The schedule: times the stream plugins go live and stop on their own, on the days ticked, in the farm's time zone.
// Each time can be for every stream or only some. Saved with its own Save (not the design's). `schedule`: { on, entries:
// [{ days: [0 (Monday) to 6], start: "HH:MM" | null, stop, streams: "all" | [ids]}] } as saved; `streams`: the stream
// plugins; `timeZone`: the farm's; `onSaved(page)`.
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const NEW_ENTRY = { days: [0, 1, 2, 3, 4], start: "08:00", stop: "18:00", streams: "all" };

export function SchedulePanel({ schedule, streams, timeZone, onSaved }) {
  const [draft, setDraft] = useState(schedule);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [said, setSaid] = useState(null);
  useEffect(() => setDraft(schedule), [JSON.stringify(schedule)]);
  const changed = JSON.stringify(draft) !== JSON.stringify(schedule);
  const set = (next) => (setDraft(next), setSaid(null), setError(null));
  const setEntry = (i, what) => set({ ...draft, entries: draft.entries.map((e, j) => (j === i ? { ...e, ...what } : e)) });
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const p = await saveStreamSchedule(draft);
      onSaved(p);
      setSaid("Saved.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div data-testid="stream-control-schedule" style={panel()}>
      <div style={{ ...heading, display: "flex", alignItems: "center", gap: 6 }}>
        <CalendarClock size={15} /> Schedule
      </div>
      <label style={label12}>
        <input type="checkbox" data-testid="stream-control-schedule-on" checked={draft.on} onChange={(e) => set({ ...draft, on: e.target.checked })} />
        Go live and stop at these times on their own
      </label>
      {draft.entries.map((e, i) => (
        <Entry key={i} e={e} streams={streams} onChange={(what) => setEntry(i, what)} onRemove={() => set({ ...draft, entries: draft.entries.filter((_, j) => j !== i) })} />
      ))}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" data-testid="stream-control-schedule-add" onClick={() => set({ ...draft, entries: [...draft.entries, NEW_ENTRY] })} style={headerButton()}>
          Add a time
        </button>
        <span style={{ flex: 1 }} />
        {changed && (
          <button type="button" onClick={() => set(schedule)} disabled={busy} style={cancelButton(busy)}>
            Discard
          </button>
        )}
        <button type="button" data-testid="stream-control-schedule-save" onClick={save} disabled={busy || !changed} style={primaryButton(busy || !changed)}>
          {busy ? "Saving…" : "Save schedule"}
        </button>
      </div>
      {error && <div style={uiText(12, c.danger, { lineHeight: 1.5 })}>{error}</div>}
      {said && !changed && <div style={uiText(12, c.green)}>{said}</div>}
      <div style={help}>
        Times are the farm's{timeZone ? ` (${timeZone})` : ""}. A stop earlier than its start is the next morning's. Leave a time empty to only
        go live, or only stop. Farmhand has to be running at the time: one it misses isn't done late. Stream control switched off
        rests the schedule too.
      </div>
    </div>
  );
}

function Entry({ e, streams, onChange, onRemove }) {
  const toggleDay = (d) => onChange({ days: e.days.includes(d) ? e.days.filter((x) => x !== d) : [...e.days, d].sort() });
  const some = e.streams !== "all";
  const toggleStream = (id) => {
    const now = some ? e.streams : [];
    onChange({ streams: now.includes(id) ? now.filter((x) => x !== id) : [...now, id] });
  };
  const time = (name) => (
    <input
      type="time" data-testid={`stream-control-schedule-${name}`} value={e[name] || ""} onChange={(ev) => onChange({ [name]: ev.target.value || null })}
      style={{ ...box(), width: 110 }}
    />
  );
  return (
    <div data-testid="stream-control-schedule-entry" style={{ display: "flex", flexDirection: "column", gap: 8, padding: 10, border: `1px solid ${c.border}`, borderRadius: 4 }}>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
        {DAYS.map((d, i) => {
          const on = e.days.includes(i);
          return (
            <button
              key={d} type="button" aria-pressed={on} onClick={() => toggleDay(i)}
              style={{ ...headerButton(), padding: "0 7px", ...(on && { color: c.amber, borderColor: c.amber, background: c.amberDim }) }}
            >
              {d}
            </button>
          );
        })}
        <span style={{ flex: 1 }} />
        <button type="button" onClick={onRemove} style={headerButton()} aria-label="Remove this time" title="Remove this time">
          <Trash2 size={13} />
        </button>
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <label style={label12}>Go live {time("start")}</label>
        <label style={label12}>Stop {time("stop")}</label>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <label style={label12}>
          <input type="radio" checked={!some} onChange={() => onChange({ streams: "all" })} />
          All streams
        </label>
        <label style={label12}>
          <input type="radio" checked={some} onChange={() => onChange({ streams: streams.map((s) => s.id).slice(0, 1) })} disabled={!streams.length} />
          Only
        </label>
        {some && streams.map((s) => (
          <label key={s.id} style={label12}>
            <input type="checkbox" checked={e.streams.includes(s.id)} onChange={() => toggleStream(s.id)} />
            {s.site}
          </label>
        ))}
      </div>
    </div>
  );
}
