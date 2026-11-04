import { useEffect, useMemo, useState } from "react";
import { c, fs, ui } from "../theme.js";
import { errorText, getEnergy } from "../api.js";
import { fieldBox, monoText, panelBox, uiText } from "../styles.js";
import { useData } from "../data.jsx";

import { SectionLabel, StatTile } from "../components/common/ui.jsx";
import { fmtCost, fmtKwh } from "../lib/format.js";
import { energyCost, parsePrice, priceForMonth } from "../lib/energyPrice.js";
import { energyByPeriod, monthIn, PeriodButtons, periodKey, periodLabel, PeriodPicker, tableHead } from "../lib/periods.jsx";

const NO_PRICES = { current: null, history: [], months: {} };

// a price as a price box shows it: empty for none
const shown = (v) => (v == null ? "" : String(v));

// A month's own price per kWh, in its row of the table: empty shows the average cost that counted that month (faint),
// typing a price gives the month its own (saved as typed, to 5 decimal places), emptying it goes back to the average.
function MonthPriceBox({ month, own, fallback, onChange }) {
  const [text, setText] = useState(shown(own));
  useEffect(() => setText((t) => (parsePrice(t) === own ? t : shown(own))), [own]);
  const bad = parsePrice(text) === undefined;
  return (
    <input
      data-testid="power-month-price"
      value={text}
      inputMode="decimal"
      placeholder={fallback == null ? "—" : String(fallback)}
      aria-label={`Price per kWh for ${month}`}
      aria-invalid={bad}
      title={own != null ? "This month's own price. Empty it to use the average cost again." : "The average cost for this month. Type a price to give this month its own."}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      onChange={(e) => {
        setText(e.target.value);
        const n = parsePrice(e.target.value);
        if (n !== undefined && n !== own) onChange(n);
      }}
      onBlur={() => setText(shown(bad ? own : parsePrice(text)))}
      style={{
        ...fieldBox(), width: "100%", boxSizing: "border-box", height: 24, padding: "0 6px", fontSize: fs(12),
        borderColor: bad ? c.amber : own != null ? c.teal : c.border,
      }}
    />
  );
}

// Each printer's colour in the bars: the scheme's own colours, in turn
const printerColor = (i) => [c.teal, c.amber, c.green, c.fileName, c.danger, c.textMuted][i % 6];

// What a kWh costs on average, in $: typed here and kept with the other settings. Saved when it's a number from 0 to
// 100 (the server's limits), to 5 decimal places (more are rounded, and the box shows the rounded price once it's
// left); emptied, it's cleared. A typo is put back when the box is left. saveState: the settings' save, so once a
// price is typed the box says "Saving…", then "Saved" (or why it couldn't be).
function EnergyPriceBox({ value, onChange, saveState }) {
  const [typed, setTyped] = useState(false); // the status only shows once a price has been typed here
  const [text, setText] = useState(shown(value));
  // a price saved elsewhere (or restored) replaces the box's text; one that's the same as what's typed ("0.10", "0.")
  // leaves the typing alone
  useEffect(() => setText((t) => (parsePrice(t) === value ? t : shown(value))), [value]);
  const change = (t) => {
    setText(t);
    const n = parsePrice(t);
    if (n !== undefined && n !== value) {
      setTyped(true);
      onChange(n);
    }
  };
  const bad = parsePrice(text) === undefined;
  const status =
    !typed || !saveState || saveState.phase === "idle" ? null
    : saveState.phase === "saving" ? { color: c.textFaint, text: "Saving…" }
    : saveState.phase === "error" ? { color: c.amber, text: "Couldn't save to the server. It's kept in this browser and sent on your next visit." }
    : { color: c.green, text: "Saved" };
  return (
    <label data-testid="energy-price" style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6, marginBottom: 10 })}>
      Average cost
      <span style={{ display: "flex", alignItems: "center", ...fieldBox(), borderColor: bad ? c.amber : c.border, height: 26, boxSizing: "border-box", padding: "0 7px", gap: 3 }}>
        <span style={{ color: c.textFaint }}>$</span>
        <input
          data-testid="energy-price-input"
          value={text}
          inputMode="decimal"
          placeholder="0.00"
          aria-label="Average cost of electricity, $ per kWh"
          aria-invalid={bad}
          title={bad ? "A price from 0 to 100, e.g. 0.15" : "What a kWh of electricity costs you on average, from this month on (earlier months keep their price)"}
          onChange={(e) => change(e.target.value)}
          onBlur={() => setText(shown(bad ? value : parsePrice(text)))}
          style={{ width: 72, background: "none", border: "none", outline: "none", color: c.textPrimary, ...ui, fontSize: fs(13), padding: 0 }}
        />
      </span>
      per kWh
      {status && (
        <span data-testid="energy-price-status" role="status" style={{ color: status.color }}>
          {status.text}
        </span>
      )}
    </label>
  );
}

// The whole farm's energy use: every printer's power meter and print energy (the same figures as each printer's own
// Energy panel), added up by month or year, with each printer's share. Any month or year can be picked to look at:
// its row, or the arrows and list at the top. prices: the price of electricity ({ current, history, months }, see
// lib/energyPrice.js); onEnergyPrice sets the average cost (the box beside the heading: counts from this month on),
// onMonthPrice(month, price | null) one month's own price (the box in its row; null = back to the average cost).
export function PowerSection({ prices = NO_PRICES, onEnergyPrice, onMonthPrice, saveState }) {
  const energyPrice = prices.current;
  const { printers } = useData();
  const [energy, setEnergy] = useState(null); // printer id -> its /energy answer, or { error }
  const [by, setBy] = useState("month");
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

  const max = Math.max(1e-9, ...periods.map((p) => Math.max(p.prints, p.whole ?? 0)));
  const current = periodKey(new Date(), by);
  const selected = picked ?? current;
  const thisPeriod = farm[selected];
  const word = selected === current ? (by === "month" ? "This month" : "This year") : periodLabel(selected, by);
  // what can be picked: every month or year with figures, and the current one even before it has any
  const choices = periods.some((p) => p.key === current) ? periods.map((p) => p.key) : [current, ...periods.map((p) => p.key)];
  const cols = "90px minmax(0, 1fr) 100px 110px 80px 90px 60px";
  const printerCols = "minmax(140px, 1fr) 120px 110px 70px 90px 100px";
  // Costs: each month's whole use at that month's price, a year being its months added up. null when no month in it
  // has both a meter figure and a price.
  const priceFor = (month) => priceForMonth(prices, month);
  const printerCost = (x, key) => energyCost(prices, (x.data?.months || []).filter((m) => monthIn(m.key, key, by)));
  const periodCost = (key) =>
    perPrinter.reduce((sum, x) => (x.has && printerCost(x, key) != null ? (sum ?? 0) + printerCost(x, key) : sum), null);
  // a year's price per kWh: its months' one price, or undefined when they differ
  const yearPrice = (year) => {
    const all = new Set(Array.from({ length: 12 }, (_, i) => priceFor(`${year}-${String(i + 1).padStart(2, "0")}`)));
    return all.size === 1 ? [...all][0] : undefined;
  };
  const costHint = energyPrice == null && !prices.history.length ? "Fill in the average cost per kWh above" : "Whole use at each month's price per kWh";

  return (
    <div data-testid="power-section" style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 900 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <SectionLabel>Total power</SectionLabel>
          {onEnergyPrice && <EnergyPriceBox value={energyPrice} onChange={onEnergyPrice} saveState={saveState} />}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <PeriodPicker testId="power-pick" by={by} current={current} choices={choices} selected={selected} onPick={setPicked} />
        <PeriodButtons
          testId="power-by"
          by={by}
          onChange={(next) => {
            setBy(next);
            setPicked(null);
          }}
        />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8 }}>
        <StatTile
          label={`${word}, whole farm`}
          value={thisPeriod?.whole != null ? fmtKwh(thisPeriod.whole) : "—"}
          hint="Every printer with a power meter, idle time included"
        />
        <StatTile
          label={`${word}, electrical cost`}
          value={fmtCost(periodCost(selected))}
          hint={costHint}
        />
        <StatTile label={`${word}, prints`} value={fmtKwh(thisPeriod?.prints ?? 0)} hint="Each print's own energy, from the printers' histories" />
        <StatTile label={`${word}, prints #`} value={(thisPeriod?.printCount ?? 0).toLocaleString()} />
        <StatTile
          label="Printers with a meter"
          value={`${metered.length} of ${active.length}`}
          hint="A printer's whole use is counted once it has a power meter set up in Moonraker"
        />
      </div>

      <div data-testid="power-periods" style={panelBox({ overflowX: "auto" })}>
        <div style={{ minWidth: 680 }}>
          <div style={tableHead(cols)}>
            <div>{by === "month" ? "Month" : "Year"}</div>
            <div>Whole farm, by printer</div>
            <div>Prints</div>
            <div>Whole farm</div>
            <div title={by === "month" ? "The month's price per kWh: type one to give a month its own" : "The year's price per kWh (change it month by month)"}>$ / kWh</div>
            <div title={costHint}>Electrical cost</div>
            <div>Prints #</div>
          </div>
          {periods.length === 0 && <div style={uiText(13, c.textMuted, { padding: 14 })}>No energy figures from any printer yet.</div>}
          {periods.map((p, i) => (
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
                {p.whole == null ? "—" : fmtKwh(p.whole)}
              </div>
              {by === "month" && onMonthPrice ? (
                <MonthPriceBox
                  month={periodLabel(p.key, by)}
                  own={prices.months?.[p.key] ?? null}
                  fallback={priceForMonth({ ...prices, months: {} }, p.key)}
                  onChange={(price) => onMonthPrice(p.key, price)}
                />
              ) : (
                <div style={monoText(12, c.textMuted)} title={yearPrice(p.key) === undefined ? "Its months have different prices" : undefined}>
                  {yearPrice(p.key) === undefined ? "varies" : yearPrice(p.key) == null ? "—" : `$${yearPrice(p.key)}`}
                </div>
              )}
              <div data-testid="power-period-cost" style={monoText(12, periodCost(p.key) == null ? c.textFaint : c.heading)}>
                {fmtCost(periodCost(p.key))}
              </div>
              <div style={monoText(12, c.textMuted)}>{p.printCount || ""}</div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div data-testid="power-printers-heading" style={uiText(13, c.textFaint, { marginBottom: 10 })}>
          By printer, {selected === current ? word.toLowerCase() : word}
        </div>
        <div data-testid="power-printers" style={panelBox({ overflowX: "auto" })}>
          <div style={{ minWidth: 660 }}>
            <div style={tableHead(printerCols)}>
              <div>Printer</div>
              <div>Meter reading</div>
              <div>Whole printer</div>
              <div>Share</div>
              <div title={costHint}>Electrical cost</div>
              <div>Prints</div>
            </div>
            {perPrinter.map((x, i) => {
              const mine = x.periods.find((p) => p.key === selected);
              const share = mine?.whole != null && thisPeriod?.whole ? Math.round((mine.whole / thisPeriod.whole) * 100) : null;
              return (
                <div
                  key={x.printer.id}
                  data-testid="power-printer"
                  style={{ display: "grid", gridTemplateColumns: printerCols, gap: 10, alignItems: "center", padding: "7px 12px", borderTop: i ? `1px solid ${c.border}` : "none" }}
                >
                  <div style={uiText(13, c.heading, { display: "flex", alignItems: "center", gap: 8, minWidth: 0 })}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: x.color, flexShrink: 0 }} />
                    {x.printer.name}
                  </div>
                  {x.data?.error ? (
                    <div style={uiText(12, c.amber, { gridColumn: "span 5" })}>Couldn't load: {x.data.error}</div>
                  ) : !x.has ? (
                    <div style={uiText(12, c.textFaint, { gridColumn: "span 5" })}>
                      {x.printer.connectionType === "prusalink" ? "PrusaLink doesn't report energy use" : "No power meter or print energy yet"}
                    </div>
                  ) : (
                    <>
                      <div style={monoText(12, c.textMuted)}>{fmtKwh(x.data.meter?.energy_kwh)}</div>
                      <div style={monoText(12, mine?.whole != null ? c.heading : c.textFaint)}>{mine?.whole != null ? fmtKwh(mine.whole) : "—"}</div>
                      <div style={monoText(12, c.textMuted)}>{share != null ? `${share}%` : "—"}</div>
                      <div data-testid="power-printer-cost" style={monoText(12, printerCost(x, selected) != null ? c.heading : c.textFaint)}>
                        {fmtCost(printerCost(x, selected))}
                      </div>
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
        Whole farm: what every printer's power meter rose by, idle time included, from the readings Farmhand takes.
        Prints: each print's own energy, from the printers' histories.
        Electrical cost: the whole farm's (or a printer's) use at each month's price per kWh. The average cost counts
        from the month it's set in on (the first one set counts for the months before it too), so changing it never
        changes a past month; a month can be given its own price in its $ / kWh box.
        Retired printers aren't counted.
      </div>
    </div>
  );
}
