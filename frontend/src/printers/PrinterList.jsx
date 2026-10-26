import { useState } from "react";
import { ArrowDown, ArrowUp, Cable, Lock, Printer, StickyNote, Wifi, Wrench } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { monoText, toolButton, uiText } from "../styles.js";
import { useData } from "../data.jsx";

import { Modal } from "../components/common/dialogs.jsx";
import { Badge, Row } from "../components/common/ui.jsx";
import { nameCollator } from "../models/modelSort.js";
import { AddPrinterForm } from "./PrinterForms.jsx";

const PRINTER_SORT_KEY = "farmhand.printerSort";

// Every printer, sorted by name (the order remembered in this browser), with "Add printer"
export function PrinterList({ setPath }) {
  const { printers, bundlesForPrinter } = useData();
  const [addPrinterOpen, setAddPrinterOpen] = useState(false);
  // The printer list's order by name ("asc" A→Z | "desc" Z→A), remembered in this browser
  const [printerSort, setPrinterSortState] = useState(() => {
    try {
      return localStorage.getItem(PRINTER_SORT_KEY) === "desc" ? "desc" : "asc";
    } catch {
      return "asc";
    }
  });
  const setPrinterSort = (dir) => {
    setPrinterSortState(dir);
    try {
      localStorage.setItem(PRINTER_SORT_KEY, dir);
    } catch {
      /* storage unavailable: it just isn't remembered */
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 14 }}>
        <button
          onClick={() => setAddPrinterOpen(true)}
          style={toolButton(13)}
        >
          <Printer size={13} />
          Add printer
        </button>
      </div>
      {addPrinterOpen && (
        <Modal title="Add printer" onClose={() => setAddPrinterOpen(false)}>
          <AddPrinterForm onClose={() => setAddPrinterOpen(false)} />
        </Modal>
      )}
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 140px 140px 90px",
            padding: "8px 16px",
            fontSize: fs(12),
            color: c.textFaint,
            borderBottom: `1px solid ${c.border}`,
            background: c.panelAlt,
          }}
        >
          <button
            data-testid="printer-sort-name"
            onClick={() => setPrinterSort(printerSort === "asc" ? "desc" : "asc")}
            title={printerSort === "asc" ? "Sorted A→Z — click for Z→A" : "Sorted Z→A — click for A→Z"}
            aria-label={printerSort === "asc" ? "Name, sorted A to Z. Click to reverse" : "Name, sorted Z to A. Click to reverse"}
            style={{ display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", padding: 0, color: c.textMuted, cursor: "pointer", ...ui, fontSize: fs(12), justifySelf: "start" }}
          >
            Name
            {printerSort === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
          </button>
          <div>Type</div>
          <div>Wired IP</div>
          <div>Wireless IP</div>
          <div>Status</div>
        </div>
        {[...printers].sort((a, b) => (printerSort === "desc" ? -1 : 1) * nameCollator.compare(a.name, b.name)).map((p) => {
          const bCount = bundlesForPrinter(p.id).length;
          return (
            <Row key={p.id} onClick={() => setPath([{ label: "Printers" }, { printerId: p.id }])}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr 140px 140px 90px",
                  width: "100%",
                  alignItems: "center",
                }}
              >
                <div style={uiText(14, c.heading, { display: "flex", alignItems: "center", gap: 8 })}>
                  <Printer size={15} color={c.textFaint} />
                  {p.name}
                  {bCount > 0 && <Lock size={12} color={c.textFaint} />}
                  {p.notes && (
                    <span data-testid="printer-has-notes" title={`Has notes: ${p.notes.slice(0, 120)}${p.notes.length > 120 ? "…" : ""}`} style={{ display: "flex" }}>
                      <StickyNote size={13} color={c.textFaint} />
                    </span>
                  )}
                  {p.service.state === "due" && (
                    <span data-testid="printer-service-due" title={`${Math.floor(p.service.hours_since).toLocaleString()} print hours since the last service`}>
                      <Badge tone="danger">
                        <Wrench size={11} />
                        {p.service.interval_hours.toLocaleString()} h service due
                      </Badge>
                    </span>
                  )}
                </div>
                <div style={uiText(13, c.textMuted)}>{p.kind}</div>
                <div style={monoText(12, p.wired ? c.textPrimary : c.textFaint, { display: "flex", alignItems: "center", gap: 6 })}>
                  {p.wired && <Cable size={12} color={c.teal} />}
                  {p.wired || "—"}
                </div>
                <div style={monoText(12, p.wireless ? c.heading : c.textFaint, { display: "flex", alignItems: "center", gap: 6 })}>
                  {p.wireless && <Wifi size={12} color={c.textFaint} />}
                  {p.wireless || "—"}
                </div>
                <div>
                  {p.decommissioned ? <Badge>decommissioned</Badge> : <Badge tone="green">active</Badge>}
                </div>
              </div>
            </Row>
          );
        })}
      </div>
    </div>
  );
}
