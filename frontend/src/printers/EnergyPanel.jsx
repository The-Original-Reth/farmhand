import { useEffect, useMemo, useState } from "react";
import { c, fs, ui } from "../theme.js";
import { headerButton, monoText, uiText } from "../styles.js";
import { errorText, getEnergy } from "../api.js";

import { SectionToggle, StatTile } from "../components/common/ui.jsx";
import { fmtKwh, fmtWhen } from "../lib/format.js";

export const periodKey = (d, by) => (by === "year" ? `${d.getFullYear()}` : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
export const periodLabel = (key, by) =>
  by === "year" ? key : new Date(Number(key.slice(0, 4)), Number(key.slice(5)) - 1, 1).toLocaleDateString(undefined, { month: "short", year: "numeric" });

// Totals per month or year, newest first. The server totals each month in this browser's time zone (prints by when
// they started; the whole printer from its meter's rise; the month of the first reading marked partial), and a year
// is its months added up.
export function energyByPeriod({ months }, by) {
  if (by !== "year") return months.map((m) => ({ key: m.key, prints: m.prints, printCount: m.print_count, whole: m.whole, partial: m.partial }));
  const rows = {};
  for (const m of months) {
    const r = (rows[m.key.slice(0, 4)] ??= { key: m.key.slice(0, 4), prints: 0, printCount: 0, whole: null, partial: false });
    r.prints += m.prints;
    r.printCount += m.print_count;
    if (m.whole != null) r.whole = (r.whole ?? 0) + m.whole;
    r.partial ||= m.partial;
  }
  return Object.values(rows).sort((a, b) => (a.key < b.key ? 1 : -1));
}

// "By month" / "By year", over an energy table (here and on the Power page)
const PERIODS = [{ value: "month", label: "By month" }, { value: "year", label: "By year" }];
export function PeriodButtons({ testId, by, onChange }) {
  return (
    <div data-testid={testId} style={{ display: "flex", gap: 6 }}>
      {PERIODS.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          aria-pressed={by === o.value}
          style={{
            ...headerButton(), border: `1px solid ${by === o.value ? c.amber : c.border}`,
            background: by === o.value ? c.amberDim : "none", color: by === o.value ? c.amber : c.textMuted,
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// The last row of an energy table that shows only the recent months or years
export function ShowAllPeriods({ count, by, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{ display: "block", width: "100%", padding: "7px 12px", border: "none", borderTop: `1px solid ${c.border}`, background: "none", color: c.textMuted, ...ui, fontSize: fs(12), cursor: "pointer" }}
    >
      Show all {count} {by === "month" ? "months" : "years"}
    </button>
  );
}

// Folds away (open/onToggle)
export function EnergyPanel({ printer, syncTick, open = true, onToggle }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [by, setBy] = useState("month");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let live = true;
    getEnergy(printer.id)
      .then((d) => live && (setData(d), setError(null)))
      .catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [printer.id, syncTick]);

  const hasAny = data && (data.meter || data.months.length > 0);
  const periods = useMemo(() => (hasAny ? energyByPeriod(data, by) : []), [data, by, hasAny]);
  const shown = showAll ? periods : periods.slice(0, by === "month" ? 12 : 5);
  const max = Math.max(1e-9, ...periods.map((p) => Math.max(p.prints, p.whole ?? 0)));
  const now = new Date();
  const thisPeriod = periods.find((p) => p.key === periodKey(now, by));
  const printsKwh = data?.print_total_kwh ?? data?.print_jobs_kwh ?? null;
  const cols = "90px minmax(0, 1fr) 100px 110px 60px";

  return (
    <div data-testid="energy-panel">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: open ? 10 : 0, flexWrap: "wrap" }}>
        <SectionToggle open={open} onToggle={onToggle} controlsId="energy-body" testId="toggle-energy" indent={20}>
          Energy
        </SectionToggle>
        {open && hasAny && (
          <PeriodButtons
            testId="energy-by"
            by={by}
            onChange={(next) => {
              setBy(next);
              setShowAll(false);
            }}
          />
        )}
      </div>
      {open && (
      <div id="energy-body" style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 14 }}>
        {error ? (
          <div style={uiText(13, c.amber)}>Couldn't load energy: {error}</div>
        ) : !data ? (
          <div style={uiText(13, c.textFaint)}>Loading…</div>
        ) : !hasAny ? (
          <div style={uiText(13, c.textMuted, { lineHeight: 1.6 })}>
            No energy figures yet. They appear once the printer has a power meter set up in Moonraker (a [sensor] with an
            energy value and history fields, e.g. a smart plug) and Farmhand has synced it.
          </div>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
              <StatTile
                label="Whole printer (meter)"
                value={fmtKwh(data.meter?.energy_kwh)}
                hint={data.meter ? `${data.meter.sensor}, read ${fmtWhen(data.meter.taken_at)}. Idle time included.` : "No meter reading yet"}
              />
              <StatTile label="Used by prints" value={fmtKwh(printsKwh)} hint="All prints the printer has recorded" />
              <StatTile label={by === "month" ? "This month, prints" : "This year, prints"} value={fmtKwh(thisPeriod?.prints ?? 0)} />
              <StatTile
                label={by === "month" ? "This month, whole printer" : "This year, whole printer"}
                value={thisPeriod?.whole != null ? fmtKwh(thisPeriod.whole) : "—"}
                hint="From the meter readings Farmhand has taken"
              />
            </div>

            <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, marginTop: 12, overflowX: "auto" }}>
              <div style={{ minWidth: 460 }}>
                <div style={{ display: "grid", gridTemplateColumns: cols, gap: 10, padding: "7px 12px", fontSize: fs(11), color: c.textFaint, background: c.panelAlt, borderBottom: `1px solid ${c.border}`, ...ui }}>
                  <div>{by === "month" ? "Month" : "Year"}</div>
                  <div />
                  <div>Prints</div>
                  <div>Whole printer</div>
                  <div>Prints #</div>
                </div>
                {shown.map((p, i) => (
                  <div
                    key={p.key}
                    data-testid="energy-period"
                    data-period={p.key}
                    style={{ display: "grid", gridTemplateColumns: cols, gap: 10, alignItems: "center", padding: "6px 12px", borderTop: i ? `1px solid ${c.border}` : "none" }}
                  >
                    <div style={uiText(12, c.textPrimary)}>{periodLabel(p.key, by)}</div>
                    <div style={{ position: "relative", height: 10 }}>
                      {p.whole != null && (
                        <div style={{ position: "absolute", inset: 0, width: `${(p.whole / max) * 100}%`, background: c.tealDim, borderRadius: 2 }} />
                      )}
                      <div style={{ position: "absolute", top: 2, bottom: 2, left: 0, width: `${(p.prints / max) * 100}%`, background: c.amber, borderRadius: 2 }} />
                    </div>
                    <div style={monoText(12, c.textPrimary)}>{fmtKwh(p.prints)}</div>
                    <div style={monoText(12, p.whole == null ? c.textFaint : c.teal)}>
                      {p.whole == null ? "—" : fmtKwh(p.whole)}
                    </div>
                    <div style={monoText(12, c.textMuted)}>{p.printCount || ""}</div>
                  </div>
                ))}
                {periods.length > shown.length && <ShowAllPeriods count={periods.length} by={by} onClick={() => setShowAll(true)} />}
              </div>
            </div>
            <div style={uiText(12, c.textFaint, { marginTop: 8, lineHeight: 1.6 })}>
              <span style={{ display: "inline-block", width: 10, height: 6, background: c.amber, borderRadius: 1, marginRight: 5 }} />
              Prints: each print's own energy, from the printer's history.{" "}
              <span style={{ display: "inline-block", width: 10, height: 6, background: c.tealDim, border: `1px solid ${c.teal}`, borderRadius: 1, margin: "0 5px 0 6px" }} />
              Whole printer, idle included: from the power meter readings Farmhand takes
              {data.meter ? ` (since ${new Date(data.meter.first_reading_at).toLocaleDateString()}).` : ", once there are some."}
            </div>
          </>
        )}
      </div>
      )}
    </div>
  );
}
