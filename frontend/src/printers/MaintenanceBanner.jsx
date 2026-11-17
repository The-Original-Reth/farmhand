import { Fragment, useEffect } from "react";
import { Wrench } from "lucide-react";
import { c, fs, ui } from "../theme.js";

const RECHECK_MS = 5 * 60 * 1000; // the printers are synced every 15 minutes in the background: look again now and then

// The printers whose 1500-hour service is due (each printer's own interval, if changed; not ones it's turned off for
// or that are decommissioned), by name
export const printersDue = (printers) =>
  printers
    .filter((p) => !p.decommissioned && p.service?.state === "due")
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }));

// The top bar's "Maintenance Required on Printer(s): ..." on every page while any printer's service is due. Each name
// opens that printer. The printers are fetched again every few minutes while the page is showing, so a printer
// that comes due (or is serviced elsewhere) shows up without reloading.
export function MaintenanceBanner({ printers, refreshPrinters, onOpenPrinter, phone }) {
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") refreshPrinters().catch(() => {}); // the list stays as it was
    }, RECHECK_MS);
    return () => clearInterval(id);
  }, [refreshPrinters]);

  const due = printersDue(printers);
  if (due.length === 0) return null;
  return (
    <div
      data-testid="maintenance-banner"
      role="status"
      style={{
        ...ui, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0,
        fontSize: fs(phone ? 14 : 15), fontWeight: 700, color: c.danger,
        justifyContent: phone ? "flex-start" : "center",
      }}
    >
      <Wrench size={16} style={{ flexShrink: 0 }} />
      <span>
        Maintenance Required on Printer(s):{" "}
        {due.map((p, i) => (
          <Fragment key={p.id}>
            {i > 0 && ", "}
            <button
              type="button"
              data-testid="maintenance-banner-printer"
              onClick={() => onOpenPrinter(p.id)}
              title={`${Math.floor(p.service.hours_since ?? 0).toLocaleString()} print hours since the last service — open ${p.name}`}
              style={{ background: "none", border: "none", padding: 0, font: "inherit", color: "inherit", textDecoration: "underline", cursor: "pointer" }}
            >
              {p.name}
            </button>
          </Fragment>
        ))}
      </span>
    </div>
  );
}
