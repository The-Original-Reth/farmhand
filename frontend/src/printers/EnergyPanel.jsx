import { useEffect, useMemo, useState } from "react";
import { c } from "../theme.js";
import { foldHeading, monoText, panelBox, uiText } from "../styles.js";
import { errorText, getEnergy } from "../api.js";

import { SectionToggle, StatTile } from "../components/common/ui.jsx";
import { fmtCost, fmtKwh, fmtWhen } from "../lib/format.js";
import { energyCost, useEnergyPrices } from "../lib/energyPrice.js";
import { energyByPeriod, monthIn, PeriodButtons, periodKey, periodLabel, ShowAllPeriods, tableHead } from "../lib/periods.jsx";

// Folds away (open/onToggle). Costs use the price per kWh set on the Power page, each month at its own price (a year
// is its months added up).
export function EnergyPanel({ printer, syncTick, open = true, onToggle }) {
  const prices = useEnergyPrices();
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
  const cols = "90px minmax(0, 1fr) 100px 80px 110px 80px 60px";
  // a month's or year's cost: its months' kWh (prints, or the whole printer) at each month's price; null when no month
  // in it has both a figure and a price
  const costOf = (key, field) => energyCost(prices, (data?.months || []).filter((m) => monthIn(m.key, key, by)), field);
  const noPrice = prices.current == null && !prices.history.length && !Object.keys(prices.months).length;
  const costHint = noPrice ? "Fill in the average cost per kWh on the Power page" : "At each month's price per kWh (set on the Power page)";
  const thisKey = periodKey(now, by);

  return (
    <div data-testid="energy-panel">
      <div style={foldHeading(open)}>
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
      <div id="energy-body" style={panelBox({ padding: 14 })}>
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
              <StatTile label={by === "month" ? "This month, prints cost" : "This year, prints cost"} value={fmtCost(costOf(thisKey, "prints"))} hint={costHint} />
              <StatTile label={by === "month" ? "This month, electrical cost" : "This year, electrical cost"} value={fmtCost(costOf(thisKey, "whole"))} hint={costHint} />
            </div>

            <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, marginTop: 12, overflowX: "auto" }}>
              <div style={{ minWidth: 640 }}>
                <div style={tableHead(cols)}>
                  <div>{by === "month" ? "Month" : "Year"}</div>
                  <div />
                  <div>Prints</div>
                  <div title={costHint}>Prints cost</div>
                  <div>Whole printer</div>
                  <div title={costHint}>Electrical cost</div>
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
                    <div data-testid="energy-prints-cost" style={monoText(12, costOf(p.key, "prints") == null ? c.textFaint : c.textPrimary)}>
                      {fmtCost(costOf(p.key, "prints"))}
                    </div>
                    <div style={monoText(12, p.whole == null ? c.textFaint : c.teal)}>
                      {p.whole == null ? "—" : fmtKwh(p.whole)}
                    </div>
                    <div data-testid="energy-whole-cost" style={monoText(12, costOf(p.key, "whole") == null ? c.textFaint : c.teal)}>
                      {fmtCost(costOf(p.key, "whole"))}
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
              {data.meter ? ` (since ${new Date(data.meter.first_reading_at).toLocaleDateString()}).` : ", once there are some."}{" "}
              Costs: each month's kWh at that month's price per kWh, set on the Power page.
            </div>
          </>
        )}
      </div>
      )}
    </div>
  );
}
