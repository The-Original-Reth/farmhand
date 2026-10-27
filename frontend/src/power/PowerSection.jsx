import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { errorText, getEnergy } from "../api.js";
import { headerButton, monoText, uiText } from "../styles.js";
import { useData } from "../data.jsx";

import { SectionLabel, StatTile } from "../components/common/ui.jsx";
import { fmtKwh } from "../lib/format.js";
import { energyByPeriod, periodKey, periodLabel } from "../printers/EnergyPanel.jsx";

// Each printer's colour in the bars: the scheme's own colours, in turn
const printerColor = (i) => [c.teal, c.amber, c.green, c.fileName, c.danger, c.textMuted][i % 6];

// The whole farm's energy use: every printer's power meter and print energy (the same figures as each printer's own
// Energy panel), added up by month or year, with each printer's share. Any month or year can be picked to look at:
// its row, or the arrows and list at the top.
export function PowerSection() {
  const { printers } = useData();
  const [energy, setEnergy] = useState(null); // printer id -> its /energy answer, or { error }
  const [by, setBy] = useState("month");
  const [showAll, setShowAll] = useState(false);
  const [picked, setPicked] = useState(null); // the month or year looked at (null = the current one)
  const active = printers.filter((p) => !p.decommissioned);
  const ids = active.map((p) => p.id).join(",");

  useEffect(() => {
    let live = true;
    Promise.all(active.map((p) => getEnergy(p.id).then((d) => [p.id, d], (e) => [p.id, { error: errorText(e) }])))
      .then((pairs) => live && setEnergy(Object.fromEntries(pairs)));
    return () => {
      live = false;
    };
  }, [ids]);

  // every printer's periods, then the farm's: worked out once per answer and grouping, not on every click
  const { perPrinter, metered, farm, periods } = useMemo(() => {
    if (!energy) return { perPrinter: [], metered: [], farm: {}, periods: [] };
    // a period's whole-farm figure adds up the printers that have readings in it
    const perPrinter = active.map((p, i) => {
      const d = energy[p.id];
      const has = d && !d.error && (d.meter || d.months.length > 0);
      return { printer: p, color: printerColor(i), data: d, has, periods: has ? energyByPeriod(d, by) : [] };
    });
    const metered = perPrinter.filter((x) => x.data?.meter);
    const farm = {};
    for (const x of perPrinter) {
      for (const p of x.periods) {
        const f = (farm[p.key] ??= { key: p.key, prints: 0, printCount: 0, whole: null, partial: false, parts: [] });
        f.prints += p.prints;
        f.printCount += p.printCount;
        if (p.whole != null) {
          f.whole = (f.whole ?? 0) + p.whole;
          f.parts.push({ color: x.color, name: x.printer.name, kwh: p.whole });
        }
        f.partial ||= p.partial;
      }
    }
    const periods = Object.values(farm).sort((a, b) => (a.key < b.key ? 1 : -1)); // newest first
    return { perPrinter, metered, farm, periods };
  }, [energy, by, printers]);

  if (!energy) return <div style={uiText(13, c.textFaint)}>Loading the farm's energy…</div>;

  const shown = showAll ? periods : periods.slice(0, by === "month" ? 12 : 5);
  const max = Math.max(1e-9, ...periods.map((p) => Math.max(p.prints, p.whole ?? 0)));
  const current = periodKey(new Date(), by);
  const selected = picked ?? current;
  const thisPeriod = farm[selected];
  const word = selected === current ? (by === "month" ? "This month" : "This year") : periodLabel(selected, by);
  // what can be picked: every month or year with figures, and the current one even before it has any
  const choices = periods.some((p) => p.key === current) ? periods.map((p) => p.key) : [current, ...periods.map((p) => p.key)];
  const at = choices.indexOf(selected);
  const step = (d) => choices[at + d] && setPicked(choices[at + d]);
  const cols = "90px minmax(0, 1fr) 100px 110px 60px";
  const head = { display: "grid", gap: 10, padding: "7px 12px", fontSize: fs(11), color: c.textFaint, background: c.panelAlt, borderBottom: `1px solid ${c.border}`, ...ui };

  return (
    <div data-testid="power-section" style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 900 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <SectionLabel>Total power</SectionLabel>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <div data-testid="power-pick" style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <button onClick={() => step(1)} disabled={at >= choices.length - 1} aria-label={by === "month" ? "Month before" : "Year before"} style={{ ...headerButton(), padding: 0, width: 26, justifyContent: "center", opacity: at >= choices.length - 1 ? 0.45 : 1 }}>
            <ChevronLeft size={14} />
          </button>
          <select
            value={selected}
            onChange={(e) => setPicked(e.target.value === current ? null : e.target.value)}
            aria-label={by === "month" ? "Month to look at" : "Year to look at"}
            style={{ ...headerButton(), padding: "0 6px", color: c.textPrimary, background: c.panelAlt }}
          >
            {choices.map((k) => (
              <option key={k} value={k}>
                {periodLabel(k, by)}
                {k === current ? (by === "month" ? " (this month)" : " (this year)") : ""}
              </option>
            ))}
          </select>
          <button onClick={() => step(-1)} disabled={at <= 0} aria-label={by === "month" ? "Month after" : "Year after"} style={{ ...headerButton(), padding: 0, width: 26, justifyContent: "center", opacity: at <= 0 ? 0.45 : 1 }}>
            <ChevronRight size={14} />
          </button>
        </div>
        <div data-testid="power-by" style={{ display: "flex", gap: 6 }}>
          {[{ value: "month", label: "By month" }, { value: "year", label: "By year" }].map((o) => (
            <button
              key={o.value}
              onClick={() => {
                setBy(o.value);
                setShowAll(false);
                setPicked(null);
              }}
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
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8 }}>
        <StatTile
          label={`${word}, whole farm`}
          value={thisPeriod?.whole != null ? `${thisPeriod.partial ? "≥ " : ""}${fmtKwh(thisPeriod.whole)}` : "—"}
          hint="Every printer with a power meter, idle time included"
        />
        <StatTile label={`${word}, prints`} value={fmtKwh(thisPeriod?.prints ?? 0)} hint="Each print's own energy, from the printers' histories" />
        <StatTile label={`${word}, prints #`} value={(thisPeriod?.printCount ?? 0).toLocaleString()} />
        <StatTile
          label="Printers with a meter"
          value={`${metered.length} of ${active.length}`}
          hint="A printer's whole use is counted once it has a power meter set up in Moonraker"
        />
      </div>

      <div data-testid="power-periods" style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, overflowX: "auto" }}>
        <div style={{ minWidth: 480 }}>
          <div style={{ ...head, gridTemplateColumns: cols }}>
            <div>{by === "month" ? "Month" : "Year"}</div>
            <div>Whole farm, by printer</div>
            <div>Prints</div>
            <div>Whole farm</div>
            <div>Prints #</div>
          </div>
          {shown.length === 0 && <div style={uiText(13, c.textMuted, { padding: 14 })}>No energy figures from any printer yet.</div>}
          {shown.map((p, i) => (
            <div
              key={p.key}
              data-testid="power-period"
              data-period={p.key}
              role="button"
              tabIndex={0}
              aria-pressed={p.key === selected}
              onClick={() => setPicked(p.key === current ? null : p.key)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setPicked(p.key === current ? null : p.key))}
              title={`Look at ${periodLabel(p.key, by)}`}
              style={{
                display: "grid", gridTemplateColumns: cols, gap: 10, alignItems: "center", padding: "6px 12px", cursor: "pointer",
                borderTop: i ? `1px solid ${c.border}` : "none", background: p.key === selected ? c.panelAlt : "none",
                boxShadow: p.key === selected ? `inset 3px 0 0 ${c.amber}` : "none",
              }}
            >
              <div style={uiText(12, p.key === selected ? c.heading : c.textPrimary)}>{periodLabel(p.key, by)}</div>
              <div style={{ display: "flex", height: 10, borderRadius: 2, overflow: "hidden" }} title={p.parts.map((x) => `${x.name}: ${fmtKwh(x.kwh)}`).join("\n")}>
                {p.parts.map((x) => (
                  <div key={x.name} style={{ width: `${(x.kwh / max) * 100}%`, background: x.color }} />
                ))}
              </div>
              <div style={monoText(12, c.textPrimary)}>{fmtKwh(p.prints)}</div>
              <div style={monoText(12, p.whole == null ? c.textFaint : c.heading)} title={p.partial ? "Some readings started part-way through this period" : undefined}>
                {p.whole == null ? "—" : `${p.partial ? "≥ " : ""}${fmtKwh(p.whole)}`}
              </div>
              <div style={monoText(12, c.textMuted)}>{p.printCount || ""}</div>
            </div>
          ))}
          {periods.length > shown.length && (
            <button
              onClick={() => setShowAll(true)}
              style={{ display: "block", width: "100%", padding: "7px 12px", border: "none", borderTop: `1px solid ${c.border}`, background: "none", color: c.textMuted, ...ui, fontSize: fs(12), cursor: "pointer" }}
            >
              Show all {periods.length} {by === "month" ? "months" : "years"}
            </button>
          )}
        </div>
      </div>

      <div>
        <div data-testid="power-printers-heading" style={uiText(13, c.textFaint, { marginBottom: 10 })}>
          By printer, {selected === current ? word.toLowerCase() : word}
        </div>
        <div data-testid="power-printers" style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, overflowX: "auto" }}>
          <div style={{ minWidth: 560 }}>
            <div style={{ ...head, gridTemplateColumns: "minmax(140px, 1fr) 120px 110px 70px 100px" }}>
              <div>Printer</div>
              <div>Meter reading</div>
              <div>Whole printer</div>
              <div>Share</div>
              <div>Prints</div>
            </div>
            {perPrinter.map((x, i) => {
              const mine = x.periods.find((p) => p.key === selected);
              const share = mine?.whole != null && thisPeriod?.whole ? Math.round((mine.whole / thisPeriod.whole) * 100) : null;
              return (
                <div
                  key={x.printer.id}
                  data-testid="power-printer"
                  style={{ display: "grid", gridTemplateColumns: "minmax(140px, 1fr) 120px 110px 70px 100px", gap: 10, alignItems: "center", padding: "7px 12px", borderTop: i ? `1px solid ${c.border}` : "none" }}
                >
                  <div style={uiText(13, c.heading, { display: "flex", alignItems: "center", gap: 8, minWidth: 0 })}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: x.color, flexShrink: 0 }} />
                    {x.printer.name}
                  </div>
                  {x.data?.error ? (
                    <div style={uiText(12, c.amber, { gridColumn: "span 4" })}>Couldn't load: {x.data.error}</div>
                  ) : !x.has ? (
                    <div style={uiText(12, c.textFaint, { gridColumn: "span 4" })}>
                      {x.printer.connectionType === "prusalink" ? "PrusaLink doesn't report energy use" : "No power meter or print energy yet"}
                    </div>
                  ) : (
                    <>
                      <div style={monoText(12, c.textMuted)}>{fmtKwh(x.data.meter?.energy_kwh)}</div>
                      <div style={monoText(12, mine?.whole != null ? c.heading : c.textFaint)}>{mine?.whole != null ? fmtKwh(mine.whole) : "—"}</div>
                      <div style={monoText(12, c.textMuted)}>{share != null ? `${share}%` : "—"}</div>
                      <div style={monoText(12, c.textPrimary)}>{fmtKwh(mine?.prints ?? 0)}</div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div style={uiText(12, c.textFaint, { lineHeight: 1.6 })}>
        Whole farm: what every printer's power meter rose by, idle time included, from the readings Farmhand takes (“≥”
        where a meter's readings began part-way through). Prints: each print's own energy, from the printers' histories.
        Retired printers aren't counted.
      </div>
    </div>
  );
}
