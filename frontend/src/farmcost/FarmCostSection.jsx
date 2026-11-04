import { useEffect, useMemo, useState } from "react";
import { Download } from "lucide-react";
import { c } from "../theme.js";
import { errorText, getEnergy, getFarmCost } from "../api.js";
import { headerButton, monoText, panelBox, uiText } from "../styles.js";
import { useData } from "../data.jsx";

import { SectionLabel, StatTile } from "../components/common/ui.jsx";
import { fmtCost as money, fmtGrams, fmtKwh } from "../lib/format.js";
import { energyCost, priceForMonth, useEnergyPrices } from "../lib/energyPrice.js";
import { BY_MONTH_YEAR_OR_ALL, monthIn, PeriodButtons, periodKey, periodLabel, PeriodPicker, tableHead } from "../lib/periods.jsx";

const add = (a, b) => (b == null ? a : (a ?? 0) + b); // null + nothing stays null: "—" rather than $0.00

// The period in a download's name: "nov 2026", "year 2026" or "all time" (whatever is on screen)
const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const fileLabel = (key, by) => (by === "all" ? "all time" : by === "year" ? `year ${key}` : `${MONTHS[Number(key.slice(5)) - 1]} ${key.slice(0, 4)}`);

// A spreadsheet of the table as shown: one row per printer and the whole farm, plain numbers (no $ or units, so Excel
// adds them up), empty where the page shows "—". Starts with a byte-order mark so Excel reads it as UTF-8.
function downloadCsv(filename, period, rows, farm) {
  const cell = (v) => {
    const s = v == null ? "" : typeof v === "number" ? String(Math.round(v * 1000) / 1000) : String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const line = (period_, name, r) =>
    [period_, name, r.prints, r.grams, r.filamentCost == null ? null : r.filamentCost.toFixed(2), r.kwh,
      r.energyCost == null ? null : r.energyCost.toFixed(2), r.total == null ? null : r.total.toFixed(2),
      r.unweighed || null, r.uncosted || null].map(cell).join(",");
  const head = ["Period", "Printer", "Prints", "Filament (g)", "Filament cost ($)", "Electricity (kWh)", "Electricity cost ($)",
    "Total cost ($)", "Prints without a weight", "Prints without a filament price"].join(",");
  const text = [head, ...rows.map((r) => line(period, r.printer.name, r)), line(period, "Whole farm", farm)].join("\r\n");
  const url = URL.createObjectURL(new Blob(["\ufeff" + text + "\r\n"], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// What the farm costs to run: the filament every printer used and what it cost (from the print histories, each print
// costed as in its print history row), and the electricity each printer used (its power meter, idle time included)
// and what that cost at each month's price per kWh from the Power page. For a month, a year, or all time, in total
// and per printer. Retired printers aren't counted, as on the Power page.
export function FarmCostSection() {
  const { printers } = useData();
  const prices = useEnergyPrices();
  const [filament, setFilament] = useState(null); // /farm-cost: printer id -> its months
  const [records, setRecords] = useState(null); // where each month's record is saved, and which are
  const [energy, setEnergy] = useState({}); // printer id -> its /energy answer, or { error }
  const [error, setError] = useState(null);
  const [by, setBy] = useState("month");
  const [picked, setPicked] = useState(null); // the month or year looked at (null = the current one)
  const active = printers.filter((p) => !p.decommissioned);
  const ids = active.map((p) => p.id).join(",");

  useEffect(() => {
    let live = true;
    getFarmCost()
      .then((r) => {
        if (!live) return;
        setFilament(Object.fromEntries(r.printers.map((p) => [p.printer_id, p.months])));
        setRecords(r.records || null);
      })
      .catch((e) => live && setError(errorText(e)));
    Promise.all(active.map((p) => getEnergy(p.id).then((d) => [p.id, d], (e) => [p.id, { error: errorText(e) }])))
      .then((pairs) => live && setEnergy(Object.fromEntries(pairs)));
    return () => {
      live = false;
    };
  }, [ids]);

  // every month or year with any figures, newest first
  const periods = useMemo(() => {
    const keys = new Set();
    for (const p of active) {
      for (const m of filament?.[p.id] || []) keys.add(by === "year" ? m.key.slice(0, 4) : m.key);
      for (const m of energy[p.id]?.months || []) keys.add(by === "year" ? m.key.slice(0, 4) : m.key);
    }
    return [...keys].sort().reverse();
  }, [filament, energy, by, ids]);

  if (error) return <div style={uiText(13, c.amber)}>Couldn't load the farm's costs: {error}</div>;
  if (!filament) return <div style={uiText(13, c.textFaint)}>Adding up the farm's costs…</div>;

  const current = by === "all" ? "all" : periodKey(new Date(), by);
  const selected = by === "all" ? "all" : picked ?? current;
  const choices = by === "all" ? [] : periods.includes(current) ? periods : [current, ...periods];
  const inPeriod = (key) => monthIn(key, selected, by);
  const word = by === "all" ? "All time" : selected === current ? (by === "month" ? "This month" : "This year") : periodLabel(selected, by);

  // one printer's figures for the period looked at
  const figures = (p) => {
    const f = { prints: 0, grams: null, filamentCost: null, unweighed: 0, uncosted: 0, kwh: null, energyCost: null, unpriced: false };
    for (const m of (filament[p.id] || []).filter((m) => inPeriod(m.key))) {
      f.prints += m.prints;
      f.unweighed += m.unweighed;
      f.uncosted += m.uncosted;
      if (m.prints > m.unweighed) f.grams = add(f.grams, m.grams);
      if (m.prints > m.uncosted) f.filamentCost = add(f.filamentCost, m.filament_cost);
    }
    const metered = (energy[p.id]?.months || []).filter((m) => inPeriod(m.key) && m.whole != null);
    for (const m of metered) f.kwh = add(f.kwh, m.whole);
    f.unpriced = metered.some((m) => priceForMonth(prices, m.key) == null);
    f.energyCost = energyCost(prices, metered);
    f.total = f.filamentCost == null && f.energyCost == null ? null : (f.filamentCost ?? 0) + (f.energyCost ?? 0);
    return f;
  };
  const rows = active.map((p) => ({ printer: p, ...figures(p) }));
  const farm = rows.reduce(
    (t, r) => ({
      grams: add(t.grams, r.grams), filamentCost: add(t.filamentCost, r.filamentCost), kwh: add(t.kwh, r.kwh),
      energyCost: add(t.energyCost, r.energyCost), total: add(t.total, r.total), prints: t.prints + r.prints,
      unweighed: t.unweighed + r.unweighed, uncosted: t.uncosted + r.uncosted, unpriced: t.unpriced || r.unpriced,
    }),
    { grams: null, filamentCost: null, kwh: null, energyCost: null, total: null, prints: 0, unweighed: 0, uncosted: 0, unpriced: false },
  );
  const cols = "minmax(140px, 1fr) 60px 100px 100px 110px 100px 100px";
  const head = tableHead(cols);
  const gaps = (r) => [
    r.unweighed ? `${r.unweighed} print${r.unweighed === 1 ? "" : "s"} without a known weight` : null,
    r.uncosted ? `${r.uncosted} print${r.uncosted === 1 ? "" : "s"} without a filament price` : null,
  ].filter(Boolean).join("; ");

  return (
    <div data-testid="farm-cost-section" style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 900 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <SectionLabel>Farm cost</SectionLabel>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
          {by !== "all" && (
            <PeriodPicker testId="farm-cost-pick" by={by} current={current} choices={choices} selected={selected} onPick={setPicked} />
          )}
          <button
            data-testid="farm-cost-csv"
            onClick={() => downloadCsv(`farmhand - farm cost - ${fileLabel(selected, by)}.csv`, by === "all" ? "All time" : selected, rows, farm)}
            title="Download this table as a CSV file, to open in Excel"
            style={headerButton()}
          >
            <Download size={13} /> Download CSV
          </button>
          <PeriodButtons
            testId="farm-cost-by"
            by={by}
            options={BY_MONTH_YEAR_OR_ALL}
            onChange={(next) => {
              setBy(next);
              setPicked(null);
            }}
          />
        </div>
      </div>

      <div data-testid="farm-cost-tiles" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
        <StatTile label={`${word}, filament used`} value={farm.grams == null ? "—" : fmtGrams(farm.grams)} hint={gaps(farm) || `${farm.prints} prints`} />
        <StatTile label={`${word}, filament cost`} value={money(farm.filamentCost)} hint={gaps(farm) || undefined} />
        <StatTile label={`${word}, electricity used`} value={farm.kwh == null ? "—" : fmtKwh(farm.kwh)} hint="Every printer with a power meter, idle time included" />
        <StatTile
          label={`${word}, electricity cost`}
          value={money(farm.energyCost)}
          hint={farm.unpriced ? "Some months have no price per kWh: fill in the average cost on the Power page" : "At each month's price per kWh (set on the Power page)"}
        />
        <StatTile label={`${word}, total cost`} value={money(farm.total)} hint="Filament cost + electricity cost" />
      </div>

      <div>
        <div style={uiText(13, c.textFaint, { marginBottom: 10 })}>By printer, {selected === current && by !== "all" ? word.toLowerCase() : word}</div>
        <div data-testid="farm-cost-printers" style={panelBox({ overflowX: "auto" })}>
          <div style={{ minWidth: 720 }}>
            <div style={head}>
              <div>Printer</div>
              <div>Prints</div>
              <div>Filament</div>
              <div>Filament cost</div>
              <div>Electricity</div>
              <div>Electricity cost</div>
              <div>Total cost</div>
            </div>
            {rows.map((r, i) => (
              <div
                key={r.printer.id}
                data-testid="farm-cost-printer"
                style={{ display: "grid", gridTemplateColumns: cols, gap: 10, alignItems: "center", padding: "7px 12px", borderTop: i ? `1px solid ${c.border}` : "none" }}
              >
                <div style={uiText(13, c.heading, { minWidth: 0, overflowWrap: "anywhere" })}>{r.printer.name}</div>
                <div style={monoText(12, c.textMuted)}>{r.prints || ""}</div>
                <div style={monoText(12, r.grams == null ? c.textFaint : c.textPrimary)} title={gaps(r) || undefined}>
                  {r.grams == null ? "—" : fmtGrams(r.grams)}
                </div>
                <div style={monoText(12, r.filamentCost == null ? c.textFaint : c.textPrimary)} title={gaps(r) || undefined}>
                  {money(r.filamentCost)}
                </div>
                <div
                  style={monoText(12, r.kwh == null ? c.textFaint : c.teal)}
                  title={r.kwh == null ? (r.printer.connectionType === "prusalink" ? "PrusaLink doesn't report energy use" : "No power meter readings") : undefined}
                >
                  {r.kwh == null ? "—" : fmtKwh(r.kwh)}
                </div>
                <div style={monoText(12, r.energyCost == null ? c.textFaint : c.teal)} title={r.unpriced ? "Some months have no price per kWh" : undefined}>
                  {money(r.energyCost)}
                </div>
                <div style={monoText(12, r.total == null ? c.textFaint : c.heading)}>{money(r.total)}</div>
              </div>
            ))}
            <div
              data-testid="farm-cost-total"
              style={{ display: "grid", gridTemplateColumns: cols, gap: 10, alignItems: "center", padding: "7px 12px", borderTop: `1px solid ${c.border}`, background: c.panelAlt }}
            >
              <div style={uiText(13, c.heading, { fontWeight: 600 })}>Whole farm</div>
              <div style={monoText(12, c.textMuted)}>{farm.prints || ""}</div>
              <div style={monoText(12, c.heading)}>{farm.grams == null ? "—" : fmtGrams(farm.grams)}</div>
              <div style={monoText(12, c.heading)}>{money(farm.filamentCost)}</div>
              <div style={monoText(12, c.heading)}>{farm.kwh == null ? "—" : fmtKwh(farm.kwh)}</div>
              <div style={monoText(12, c.heading)}>{money(farm.energyCost)}</div>
              <div style={monoText(12, c.heading)}>{money(farm.total)}</div>
            </div>
          </div>
        </div>
      </div>

      {records && (
        <div data-testid="farm-cost-records" style={panelBox({ padding: "10px 14px" })}>
          <div style={uiText(13, c.heading, { marginBottom: 4 })}>Monthly records</div>
          {records.problem ? (
            <div style={uiText(12, c.amber, { lineHeight: 1.6 })}>
              Last month's record can't be saved right now: {records.problem} It's tried again every hour.
            </div>
          ) : (
            <div style={uiText(12, c.textMuted, { lineHeight: 1.6 })}>
              When a month ends, its table is saved as a CSV in{" "}
              <span style={monoText(12, c.textPrimary)}>{records.folder}</span> (chosen in Settings), once, and never
              replaced.{" "}
              {records.saved.length
                ? `Saved so far: ${records.saved.map((n) => n.replace(/^farmhand - farm cost - |\.csv$/g, "")).join(", ")}.`
                : "None saved yet: the first is saved once this month is over."}
            </div>
          )}
        </div>
      )}

      <div style={uiText(12, c.textFaint, { lineHeight: 1.6 })}>
        Filament: every print in the printers' histories that used filament, in the month it started, weighed and
        costed as in its print history (the G-code's own filament price, density and diameter, else its 3MF's). Prints
        without a known weight or price are left out of those figures (hover to see how many). Electricity: each
        printer's power meter, idle time included, at each month's price per kWh from the Power page. Retired printers
        aren't counted.
      </div>
    </div>
  );
}
