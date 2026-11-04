import { useEffect, useRef, useState } from "react";
import { c, fs, ui } from "../theme.js";
import { fieldBox, foldHeading, monoText, uiText } from "../styles.js";
import { errorText, getPrintJobs } from "../api.js";

import { Badge, SectionToggle } from "../components/common/ui.jsx";
import { fmtCost, fmtDuration, fmtGrams, fmtKwh, fmtMetres, fmtMoney, fmtWhen } from "../lib/format.js";

// ---- print history: Farmhand's copy ----
const JOB_STATUS_TONE = { completed: "green", in_progress: "teal", cancelled: "muted" };
const JOB_FILTERS = [
  { value: "", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];
const HISTORY_PAGE = 25;

// The hover hint on a print's filament cost: how it was worked out, or why there's none
const costHint = (j) => {
  const d = j.filament_cost_detail;
  if (!d) {
    return j.filament_used > 0
      ? "No filament price yet: the G-code hasn't been read from the printer (or has none), and no 3MF on this printer has this file's name"
      : "No filament used";
  }
  const n = (v, digits) => v.toLocaleString(undefined, { maximumFractionDigits: digits });
  const from = d.source === "gcode" ? "the price in the printed G-code" : d.filename;
  return `${n(d.grams, 1)} g at $${fmtMoney(d.cost_per_kg)} per kg (${n(d.diameter, 2)} mm, ${n(d.density, 3)} g/cm³), from ${from}`;
};

// open / onToggle: whether the list is folded away (only its heading and count show then)
export function PrintHistory({ printer, syncTick, open = true, onToggle }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(null);
  const [kwhPrice, setKwhPrice] = useState(null); // $ per kWh from the Power page, as the server answered with the list
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const ask = useRef(0);

  const load = async (offset) => {
    const mine = ++ask.current;
    setLoading(true);
    try {
      const r = await getPrintJobs(printer.id, { limit: HISTORY_PAGE, offset, status, q });
      if (mine !== ask.current) return;
      setJobs((prev) => (offset ? [...prev, ...r.jobs] : r.jobs));
      setTotal(r.total);
      setKwhPrice(r.energy_price_per_kwh ?? null);
      setError(null);
    } catch (e) {
      if (mine === ask.current) setError(errorText(e));
    } finally {
      if (mine === ask.current) setLoading(false);
    }
  };
  useEffect(() => {
    const t = setTimeout(() => load(0), q ? 250 : 0); // a short pause while typing
    return () => clearTimeout(t);
  }, [printer.id, status, q, syncTick]);

  const control = fieldBox();
  const cols = "minmax(140px, 170px) minmax(200px, 1fr) 100px 90px 80px 90px 80px 90px 80px"; // below ~1030px wide the table scrolls sideways
  return (
    <div data-testid="print-history">
      <div style={foldHeading(open)}>
        <SectionToggle open={open} onToggle={onToggle} controlsId="print-history-body" testId="toggle-history">
          Print history
          {total != null && <span style={{ color: c.textFaint }}>({total.toLocaleString()} {total === 1 ? "print" : "prints"})</span>}
        </SectionToggle>
        {open && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            data-testid="print-history-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search file names…"
            aria-label="Search print history"
            style={{ ...control, padding: "5px 9px", width: 200 }}
          />
          <select data-testid="print-history-filter" value={status} onChange={(e) => setStatus(e.target.value)} style={{ ...control, padding: "5px 8px" }}>
            {JOB_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
        )}
      </div>
      <div id="print-history-body" style={{ display: open ? "block" : "none", border: `1px solid ${c.border}`, borderRadius: 4, overflowX: "auto", background: c.panel }}>
        <div style={{ minWidth: 1030 }}>
        <div style={{ display: "grid", gridTemplateColumns: cols, gap: 10, padding: "7px 14px", fontSize: fs(11), color: c.textFaint, background: c.panelAlt, borderBottom: `1px solid ${c.border}`, ...ui }}>
          <div>Started</div>
          <div>File</div>
          <div>Status</div>
          <div>Print time</div>
          <div>Filament</div>
          <div title="The filament used, at the 3MF's filament price per kg">Filament cost</div>
          <div>Energy</div>
          <div title={kwhPrice == null ? "Fill in the average cost per kWh on the Power page" : "The print's energy at its month's price per kWh (set on the Power page)"}>Energy cost</div>
          <div title="Filament cost + energy cost (the filament cost alone when there's no energy cost)">Total cost</div>
        </div>
        {error && <div style={uiText(13, c.amber, { padding: 14 })}>Couldn't load the history: {error}</div>}
        {!error && jobs.length === 0 && (
          <div style={uiText(13, c.textMuted, { padding: 14 })}>
            {loading ? "Loading…" : q || status ? "No prints match." : "No print history yet. It's copied from the printer when it can be reached."}
          </div>
        )}
        {jobs.map((j, i) => (
          <div
            key={j.id}
            data-testid="print-job"
            data-status={j.status}
            style={{ display: "grid", gridTemplateColumns: cols, gap: 10, alignItems: "center", padding: "7px 14px", borderTop: i ? `1px solid ${c.border}` : "none" }}
          >
            <div style={monoText(12, c.textMuted)}>{fmtWhen(j.start_time)}</div>
            <div style={monoText(12, c.textPrimary, { overflowWrap: "anywhere" })} title={j.filename}>
              {j.filename}
            </div>
            <div>
              <Badge tone={JOB_STATUS_TONE[j.status] || "danger"}>{j.status.replace(/_/g, " ")}</Badge>
            </div>
            <div style={monoText(12, c.textMuted)}>{fmtDuration(j.print_duration)}</div>
            <div
              data-testid="print-job-filament"
              style={monoText(12, c.textMuted)}
              title={j.filament_grams != null ? `${fmtMetres(j.filament_used)} of filament` : "Grams aren't known for this print: no filament density or slicer estimate"}
            >
              {j.filament_grams != null ? fmtGrams(j.filament_grams) : fmtMetres(j.filament_used)}
            </div>
            <div data-testid="print-job-cost" style={monoText(12, j.filament_cost == null ? c.textFaint : c.textMuted)} title={costHint(j)}>
              {fmtCost(j.filament_cost)}
            </div>
            <div
              style={monoText(12, j.energy_kwh == null ? c.textFaint : c.textMuted)}
              title={j.avg_power_w != null ? `Average ${Math.round(j.avg_power_w)} W${j.max_power_w != null ? `, peak ${Math.round(j.max_power_w)} W` : ""}` : undefined}
            >
              {j.energy_kwh == null ? "—" : fmtKwh(j.energy_kwh)}
            </div>
            <div
              data-testid="print-job-energy-cost"
              style={monoText(12, j.energy_cost == null ? c.textFaint : c.textMuted)}
              title={j.energy_cost != null ? `${fmtKwh(j.energy_kwh)} at $${j.energy_price} per kWh` : j.energy_kwh == null ? "No energy figure for this print" : "No price per kWh for this month: fill in the average cost on the Power page"}
            >
              {fmtCost(j.energy_cost)}
            </div>
            <div
              data-testid="print-job-total-cost"
              style={monoText(12, j.total_cost == null ? c.textFaint : c.heading)}
              title={j.total_cost == null ? "No filament cost for this print" : j.energy_cost == null ? "Filament cost only (no energy cost)" : `$${fmtMoney(j.filament_cost)} filament + $${fmtMoney(j.energy_cost)} energy`}
            >
              {fmtCost(j.total_cost)}
            </div>
          </div>
        ))}
        {total != null && jobs.length < total && (
          <button
            data-testid="print-history-more"
            onClick={() => load(jobs.length)}
            disabled={loading}
            style={{ display: "block", width: "100%", padding: "8px 14px", border: "none", borderTop: `1px solid ${c.border}`, background: "none", color: c.textMuted, ...ui, fontSize: fs(12), cursor: loading ? "default" : "pointer" }}
          >
            {loading ? "Loading…" : `Show ${Math.min(HISTORY_PAGE, total - jobs.length)} more`}
          </button>
        )}
        </div>
      </div>
    </div>
  );
}
