import { useEffect, useMemo, useState } from "react";
import { Download, GripVertical, X } from "lucide-react";
import { c } from "../theme.js";
import { errorText, getEnergy, getFarmCost } from "../api.js";
import { headerButton, monoText, panelBox, uiText } from "../styles.js";
import { useData } from "../data.jsx";
import { arranged, moved } from "../lib/order.js";

import { SectionLabel, StatTile } from "../components/common/ui.jsx";
import { fmtCost as money, fmtGrams, fmtKwh, plural } from "../lib/format.js";
import { energyCost, priceForMonth, useEnergyPrices } from "../lib/energyPrice.js";
import { PeriodButtons, periodKey, periodLabel, PeriodPicker, tableHead } from "../lib/periods.jsx";

const add = (a, b) => (b == null ? a : (a ?? 0) + b); // null + nothing stays null: "—" rather than $0.00

// The period in a download's name: "nov 2026" or "year 2026" (whatever is on screen)
const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const fileLabel = (key, by) => (by === "year" ? `year ${key}` : `${MONTHS[Number(key.slice(5)) - 1]} ${key.slice(0, 4)}`);

// A day ("2026-11-04") as a row of a printer's month: "Wed, Nov 4"
const dayLabel = (key) =>
  new Date(Number(key.slice(0, 4)), Number(key.slice(5, 7)) - 1, Number(key.slice(8))).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

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

const BLANK = { prints: 0, grams: null, filamentCost: null, unweighed: 0, uncosted: 0, kwh: null, energyCost: null, unpriced: false };

// A printer's figures from its rows whose key passes `keep`: `prints` its filament by month or day (/farm-cost), `meter`
// its electricity by month or day. A day's electricity is priced at its month's price.
function figuresOf({ prints, meter }, keep, prices) {
  const f = { ...BLANK };
  for (const m of prints.filter((m) => keep(m.key))) {
    f.prints += m.prints;
    f.unweighed += m.unweighed;
    f.uncosted += m.uncosted;
    if (m.prints > m.unweighed) f.grams = add(f.grams, m.grams);
    if (m.prints > m.uncosted) f.filamentCost = add(f.filamentCost, m.filament_cost);
  }
  const metered = meter.filter((m) => keep(m.key) && m.whole != null).map((m) => ({ ...m, key: m.key.slice(0, 7) }));
  for (const m of metered) f.kwh = add(f.kwh, m.whole);
  f.unpriced = metered.some((m) => priceForMonth(prices, m.key) == null);
  f.energyCost = energyCost(prices, metered);
  f.total = f.filamentCost == null && f.energyCost == null ? null : (f.filamentCost ?? 0) + (f.energyCost ?? 0);
  return f;
}

// The whole farm: every printer's figures added up
const addUp = (rows) =>
  rows.reduce(
    (t, r) => ({
      grams: add(t.grams, r.grams), filamentCost: add(t.filamentCost, r.filamentCost), kwh: add(t.kwh, r.kwh),
      energyCost: add(t.energyCost, r.energyCost), total: add(t.total, r.total), prints: t.prints + r.prints,
      unweighed: t.unweighed + r.unweighed, uncosted: t.uncosted + r.uncosted, unpriced: t.unpriced || r.unpriced,
    }),
    { ...BLANK, total: null },
  );

// What hovering filament figures says: how many prints were left out of them, and why
const gaps = (r) => [
  r.unweighed ? `${plural(r.unweighed, "print")} without a known weight` : null,
  r.uncosted ? `${plural(r.uncosted, "print")} without a filament price` : null,
].filter(Boolean).join("; ");

const orDash = (v, format) => (v == null ? "—" : format(v));

const COLS = "minmax(140px, 1fr) 60px 100px 100px 110px 100px 100px";
const ROW = { display: "grid", gridTemplateColumns: COLS, gap: 10, alignItems: "center", padding: "7px 12px" };

// A table of figures: the header (its first column named `first`), then `children`, its rows
function FigureTable({ testId, first, children }) {
  return (
    <div data-testid={testId} style={panelBox({ overflowX: "auto" })}>
      <div style={{ minWidth: 720 }}>
        <div style={tableHead(COLS)}>
          <div>{first}</div>
          <div>Prints</div>
          <div>Filament</div>
          <div>Filament cost</div>
          <div>Electricity</div>
          <div>Electricity cost</div>
          <div>Total cost</div>
        </div>
        {children}
      </div>
    </div>
  );
}

// The figures of a row, after its name. whole: the Whole farm row (all in the heading colour, no hover text);
// kwhTitle / unpricedTitle: what hovering the electricity / its cost says (the latter only when a month has no price)
function FigureCells({ f, whole = false, kwhTitle, unpricedTitle }) {
  const tone = (v, color) => (whole ? c.heading : v == null ? c.textFaint : color);
  const left = whole ? undefined : gaps(f) || undefined;
  return (
    <>
      <div style={monoText(12, c.textMuted)}>{f.prints || ""}</div>
      <div style={monoText(12, tone(f.grams, c.textPrimary))} title={left}>{orDash(f.grams, fmtGrams)}</div>
      <div style={monoText(12, tone(f.filamentCost, c.textPrimary))} title={left}>{money(f.filamentCost)}</div>
      <div style={monoText(12, tone(f.kwh, c.teal))} title={kwhTitle}>{orDash(f.kwh, fmtKwh)}</div>
      <div style={monoText(12, tone(f.energyCost, c.teal))} title={!whole && f.unpriced ? unpricedTitle : undefined}>{money(f.energyCost)}</div>
      <div style={monoText(12, tone(f.total, c.heading))}>{money(f.total)}</div>
    </>
  );
}

// The printer clicked, in the period looked at: `rows` its days (byDay) or months, newest first
function PrinterParts({ printer, period, byDay, rows, onClose }) {
  return (
    <div data-testid="farm-cost-printer-months">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
        <div style={uiText(13, c.textFaint)}>
          <span style={{ color: c.heading }}>{printer.name}</span>, {period} {byDay ? "day by day" : "month by month"}
        </div>
        <button data-testid="farm-cost-printer-months-close" onClick={onClose} style={headerButton()}>
          <X size={13} /> Close
        </button>
      </div>
      <FigureTable first={byDay ? "Day" : "Month"}>
        {rows.length === 0 && <div style={uiText(13, c.textFaint, { padding: "10px 12px" })}>No prints or power meter readings in {period}.</div>}
        {rows.map((m, i) => (
          <div key={m.key} data-testid="farm-cost-printer-month" style={{ ...ROW, borderTop: i ? `1px solid ${c.border}` : "none" }}>
            <div style={uiText(13, c.heading)}>{byDay ? dayLabel(m.key) : periodLabel(m.key, "month")}</div>
            <FigureCells f={m} unpricedTitle="No price per kWh for this month" />
          </div>
        ))}
      </FigureTable>
    </div>
  );
}

// Where each month's table is saved once the month is over, and which are
function Records({ records }) {
  return (
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
  );
}

// What the farm costs to run: the filament every printer used and what it cost (from the print histories, each print
// costed as in its print history row), and the electricity each printer used (its power meter, idle time included)
// and what that cost at each month's price per kWh from the Power page. For a month or a year, in total and per
// printer; a printer clicked shows its month day by day, or its year month by month. Retired printers aren't counted,
// as on the Power page. The printers are listed in `order` (printer ids, kept on the server; the rest after, by name):
// drag one onto another, or Alt+Up / Alt+Down on one, to move it, and onOrder(ids) is given the new order.
export function FarmCostSection({ order = [], onOrder }) {
  const { printers } = useData();
  const prices = useEnergyPrices();
  const [filament, setFilament] = useState(null); // /farm-cost: printer id -> its months
  const [daily, setDaily] = useState({}); // /farm-cost: printer id -> { filament: its days, energy: its electricity's days }
  const [records, setRecords] = useState(null); // where each month's record is saved, and which are
  const [energy, setEnergy] = useState({}); // printer id -> its /energy answer, or { error }
  const [error, setError] = useState(null);
  const [by, setBy] = useState("month");
  const [picked, setPicked] = useState(null); // the month or year looked at (null = the current one)
  const [opened, setOpened] = useState(null); // the printer clicked in the table, whose days or months are shown
  const [dragging, setDragging] = useState(null); // the printer being dragged to a new place
  const [over, setOver] = useState(null); // the printer it's over: where it would go
  const listed = printers.filter((p) => !p.decommissioned);
  const ids = listed.map((p) => p.id).join(",");
  const keys = arranged(listed.map((p) => p.id), order);
  const active = keys.map((id) => listed.find((p) => p.id === id));

  useEffect(() => {
    let live = true;
    getFarmCost()
      .then((r) => {
        if (!live) return;
        setFilament(Object.fromEntries(r.printers.map((p) => [p.printer_id, p.months])));
        setDaily(Object.fromEntries(r.printers.map((p) => [p.printer_id, { filament: p.days || [], energy: p.energy_days || [] }])));
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

  const current = periodKey(new Date(), by);
  const selected = picked ?? current;
  const choices = periods.includes(current) ? periods : [current, ...periods];
  const inPeriod = (key) => key.startsWith(selected); // a month ("2026-03") or day ("2026-03-04") in the period looked at
  const word = selected === current ? (by === "month" ? "This month" : "This year") : periodLabel(selected, by);
  const byDay = by === "month"; // a printer clicked shows its month day by day, its year month by month

  // a printer's rows by month, or by day
  const rowsOf = (id, days) =>
    days
      ? { prints: daily[id]?.filament || [], meter: daily[id]?.energy || [] }
      : { prints: filament[id] || [], meter: energy[id]?.months || [] };
  const rows = active.map((p) => ({ printer: p, ...figuresOf(rowsOf(p.id, false), inPeriod, prices) }));
  const farm = addUp(rows);

  // the printer clicked: the days or months of the period looked at with any figures, newest first
  const openedPrinter = active.find((p) => p.id === opened);
  const parts = rowsOf(opened, byDay);
  const partRows = openedPrinter
    ? [...new Set([...parts.prints, ...parts.meter].map((m) => m.key).filter(inPeriod))]
        .sort()
        .reverse()
        .map((key) => ({ key, ...figuresOf(parts, (k) => k === key, prices) }))
    : [];
  const toggle = (id) => setOpened(opened === id ? null : id);
  const drop = (target) => {
    if (dragging != null && target != null && target !== dragging) onOrder(moved(keys, dragging, target)); // null: let go elsewhere
    setDragging(null);
    setOver(null);
  };
  // a line where the dragged printer would land: below the one it's over when going down, above it when going up
  const landing = (id) =>
    dragging == null || over !== id || id === dragging ? "none" : `inset 0 ${keys.indexOf(dragging) < keys.indexOf(id) ? -2 : 2}px 0 ${c.amber}`;

  return (
    <div data-testid="farm-cost-section" style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 900 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <SectionLabel>Farm cost</SectionLabel>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
          <PeriodPicker testId="farm-cost-pick" by={by} current={current} choices={choices} selected={selected} onPick={setPicked} />
          <button
            data-testid="farm-cost-csv"
            onClick={() => downloadCsv(`farmhand - farm cost - ${fileLabel(selected, by)}.csv`, selected, rows, farm)}
            title="Download this table as a CSV file, to open in Excel"
            style={headerButton()}
          >
            <Download size={13} /> Download CSV
          </button>
          <PeriodButtons
            testId="farm-cost-by"
            by={by}
            onChange={(next) => {
              setBy(next);
              setPicked(null);
            }}
          />
        </div>
      </div>

      <div data-testid="farm-cost-tiles" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
        <StatTile label={`${word}, filament used`} value={orDash(farm.grams, fmtGrams)} hint={gaps(farm) || `${farm.prints} prints`} />
        <StatTile label={`${word}, filament cost`} value={money(farm.filamentCost)} hint={gaps(farm) || undefined} />
        <StatTile label={`${word}, electricity used`} value={orDash(farm.kwh, fmtKwh)} hint="Every printer with a power meter, idle time included" />
        <StatTile
          label={`${word}, electricity cost`}
          value={money(farm.energyCost)}
          hint={farm.unpriced ? "Some months have no price per kWh: fill in the average cost on the Power page" : "At each month's price per kWh (set on the Power page)"}
        />
        <StatTile label={`${word}, total cost`} value={money(farm.total)} hint="Filament cost + electricity cost" />
      </div>

      <div>
        <div style={uiText(13, c.textFaint, { marginBottom: 10 })}>
          By printer, {selected === current ? word.toLowerCase() : word}. Click a printer to see its cost {byDay ? "day by day" : "month by month"}; drag one to move it.
        </div>
        <FigureTable testId="farm-cost-printers" first="Printer">
          {rows.map((r, i) => (
            <div
              key={r.printer.id}
              data-testid="farm-cost-printer"
              role="button"
              tabIndex={0}
              aria-pressed={opened === r.printer.id}
              title={`${opened === r.printer.id ? "Click to hide it again" : `Click to see this printer's cost ${byDay ? "day by day" : "month by month"}`}; drag to move it`}
              onClick={() => toggle(r.printer.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggle(r.printer.id);
                } else if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
                  e.preventDefault();
                  const next = keys[i + (e.key === "ArrowUp" ? -1 : 1)];
                  if (next != null) onOrder(moved(keys, r.printer.id, next));
                }
              }}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", r.printer.name); // Firefox only drags with something set
                setDragging(r.printer.id);
              }}
              onDragOver={(e) => {
                if (dragging == null) return;
                e.preventDefault();
                setOver(r.printer.id);
              }}
              onDrop={(e) => {
                e.preventDefault();
                drop(r.printer.id);
              }}
              onDragEnd={() => drop(null)}
              style={{
                ...ROW, cursor: "pointer", borderTop: i ? `1px solid ${c.border}` : "none", background: opened === r.printer.id ? c.amberDim : "none",
                opacity: dragging === r.printer.id ? 0.5 : 1, boxShadow: landing(r.printer.id),
              }}
            >
              <div style={uiText(13, c.heading, { minWidth: 0, overflowWrap: "anywhere", display: "flex", alignItems: "center", gap: 4 })}>
                <GripVertical size={13} color={c.textFaint} style={{ flexShrink: 0, cursor: "grab" }} aria-hidden />
                {r.printer.name}
              </div>
              <FigureCells
                f={r}
                kwhTitle={r.kwh == null ? (r.printer.connectionType === "prusalink" ? "PrusaLink doesn't report energy use" : "No power meter readings") : undefined}
                unpricedTitle="Some months have no price per kWh"
              />
            </div>
          ))}
          <div data-testid="farm-cost-total" style={{ ...ROW, borderTop: `1px solid ${c.border}`, background: c.panelAlt }}>
            <div style={uiText(13, c.heading, { fontWeight: 600 })}>Whole farm</div>
            <FigureCells f={farm} whole />
          </div>
        </FigureTable>
      </div>

      {openedPrinter && (
        <PrinterParts printer={openedPrinter} period={periodLabel(selected, by)} byDay={byDay} rows={partRows} onClose={() => setOpened(null)} />
      )}

      {records && <Records records={records} />}

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
