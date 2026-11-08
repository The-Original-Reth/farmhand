// Months and years, as the pages that add things up by period show them (Power, Farm cost, a printer's Energy).
// A month's key is "2026-03", a year's "2026"; `by` is "month" or "year".
import { ChevronLeft, ChevronRight } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { headerButton } from "../styles.js";

export const periodKey = (d, by) => (by === "year" ? `${d.getFullYear()}` : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
export const periodLabel = (key, by) =>
  by === "year" ? key : new Date(Number(key.slice(0, 4)), Number(key.slice(5)) - 1, 1).toLocaleDateString(undefined, { month: "short", year: "numeric" });
// whether a month ("2026-03") falls in the period `key` (a month or a year)
export const monthIn = (month, key, by) => (by === "year" ? month.startsWith(key) : month === key);

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

// "By month" / "By year", above a table added up by period
const BY_MONTH_OR_YEAR = [{ value: "month", label: "By month" }, { value: "year", label: "By year" }];
export function PeriodButtons({ testId, by, onChange, options = BY_MONTH_OR_YEAR }) {
  return (
    <div data-testid={testId} style={{ display: "flex", gap: 6 }}>
      {options.map((o) => (
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

// The month or year looked at: arrows to the one before and after, and a list of them all (`choices`, newest first,
// the current one marked). onPick(key) is given null for the current one.
export function PeriodPicker({ testId, by, current, choices, selected, onPick }) {
  const at = choices.indexOf(selected);
  const pick = (key) => key && onPick(key === current ? null : key);
  const arrow = { ...headerButton(), padding: 0, width: 26, justifyContent: "center" };
  const month = by === "month";
  return (
    <div data-testid={testId} style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <button onClick={() => pick(choices[at + 1])} disabled={at >= choices.length - 1} aria-label={month ? "Month before" : "Year before"} style={{ ...arrow, opacity: at >= choices.length - 1 ? 0.45 : 1 }}>
        <ChevronLeft size={14} />
      </button>
      <select
        value={selected}
        onChange={(e) => pick(e.target.value)}
        aria-label={month ? "Month to look at" : "Year to look at"}
        style={{ ...headerButton(), padding: "0 6px", color: c.textPrimary, background: c.panelAlt }}
      >
        {choices.map((k) => (
          <option key={k} value={k}>
            {periodLabel(k, by)}
            {k === current ? (month ? " (this month)" : " (this year)") : ""}
          </option>
        ))}
      </select>
      <button onClick={() => pick(choices[at - 1])} disabled={at <= 0} aria-label={month ? "Month after" : "Year after"} style={{ ...arrow, opacity: at <= 0 ? 0.45 : 1 }}>
        <ChevronRight size={14} />
      </button>
    </div>
  );
}

// The last row of a table that shows only the recent months or years
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

// The header row of such a table: small faint labels on a shaded strip (gridTemplateColumns: `cols`)
export const tableHead = (cols) => ({
  display: "grid", gridTemplateColumns: cols, gap: 10, padding: "7px 12px", fontSize: fs(11), color: c.textFaint,
  background: c.panelAlt, borderBottom: `1px solid ${c.border}`, ...ui,
});
