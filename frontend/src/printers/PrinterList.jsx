import { useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Cable, ExternalLink, Lock, Printer, StickyNote, Wifi, Wrench } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { headerButton, monoText, toolButton, uiText } from "../styles.js";
import { useData } from "../data.jsx";

import { Modal } from "../components/common/dialogs.jsx";
import { Badge, Row } from "../components/common/ui.jsx";
import { writeStored } from "../lib/storage.js";
import { nameCollator } from "../models/modelSort.js";
import { AddPrinterForm } from "./PrinterForms.jsx";
import { notesHint } from "../lib/format.js";

const PRINTER_SORT_KEY = "farmhand.printerSort";
const SORTS = { name: "Name", kind: "Type", wired: "Wired IP", wireless: "Wireless IP" }; // the columns the list sorts by

// The order remembered in this browser: { key, dir }. An older Farmhand kept just "asc" or "desc", for the name.
function loadSort() {
  try {
    const raw = localStorage.getItem(PRINTER_SORT_KEY);
    if (raw === "asc" || raw === "desc") return { key: "name", dir: raw };
    const s = JSON.parse(raw);
    return SORTS[s?.key] && (s.dir === "asc" || s.dir === "desc") ? s : { key: "name", dir: "asc" };
  } catch {
    return { key: "name", dir: "asc" };
  }
}

// IP addresses in number order (10.0.6.9 before 10.0.6.21); anything else after them, by its text
const ipKey = (ip) => {
  const parts = /^\d{1,3}(\.\d{1,3}){3}$/.test(ip) ? ip.split(".").map(Number) : null;
  return parts ? parts.reduce((n, x) => n * 256 + x, 0) : null;
};
function compareIp(a, b) {
  const x = ipKey(a), y = ipKey(b);
  if (x !== null && y !== null) return x - y;
  if (x !== null || y !== null) return x !== null ? -1 : 1;
  return nameCollator.compare(a, b);
}

// The printers in the chosen order. Ones without the value sorted by (no wireless IP, say) go last either way, and
// ties go by name.
function sorted(printers, { key, dir }) {
  const sign = dir === "desc" ? -1 : 1;
  const byName = (a, b) => nameCollator.compare(a.name, b.name);
  return [...printers].sort((a, b) => {
    if (key === "name") return sign * byName(a, b);
    const x = a[key] || "", y = b[key] || "";
    if (!x || !y) return x === y ? byName(a, b) : x ? -1 : 1;
    const d = key === "kind" ? nameCollator.compare(x, y) : compareIp(x, y);
    return d ? sign * d : byName(a, b);
  });
}
const COLUMNS = "1fr 1fr 120px 140px 140px 90px"; // name, type, web UI, wired IP, wireless IP, status

// Every printer, sorted by name (the order remembered in this browser), with "Add printer"
export function PrinterList({ setPath }) {
  const { printers, bundlesForPrinter } = useData();
  const [addPrinterOpen, setAddPrinterOpen] = useState(false);
  // The printer list's order: a column (SORTS) and "asc" | "desc", remembered in this browser
  const [printerSort, setPrinterSortState] = useState(loadSort);
  // a column's arrow: the first click sorts by it A→Z (or low to high), the next reverses it
  const sortBy = (key) => {
    const next = { key, dir: printerSort.key === key && printerSort.dir === "asc" ? "desc" : "asc" };
    setPrinterSortState(next);
    writeStored(PRINTER_SORT_KEY, next);
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
            gridTemplateColumns: COLUMNS,
            padding: "8px 16px",
            fontSize: fs(12),
            color: c.textFaint,
            borderBottom: `1px solid ${c.border}`,
            background: c.panelAlt,
          }}
        >
          <SortHeading id="name" sort={printerSort} onSort={sortBy} />
          <SortHeading id="kind" sort={printerSort} onSort={sortBy} />
          <div>Web UI</div>
          <SortHeading id="wired" sort={printerSort} onSort={sortBy} />
          <SortHeading id="wireless" sort={printerSort} onSort={sortBy} />
          <div>Status</div>
        </div>
        {sorted(printers, printerSort).map((p) => {
          const bCount = bundlesForPrinter(p.id).length;
          return (
            <Row key={p.id} onClick={() => setPath([{ label: "Printers" }, { printerId: p.id }])}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: COLUMNS,
                  width: "100%",
                  alignItems: "center",
                }}
              >
                <div style={uiText(14, c.heading, { display: "flex", alignItems: "center", gap: 8 })}>
                  <Printer size={15} color={c.textFaint} />
                  {p.name}
                  {bCount > 0 && <Lock size={12} color={c.textFaint} />}
                  {p.notes && (
                    <span data-testid="printer-has-notes" title={notesHint(p.notes)} style={{ display: "flex" }}>
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
                <div>
                  <WebUiButton printer={p} />
                </div>
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

// Opens the printer's own web page in a new tab: PrusaLink for a Prusa reached that way, Mainsail for a Klipper one.
// With no address it shows "—" in the list (`orDash`), or nothing; `style` dresses it like the buttons beside it.
export function WebUiButton({ printer, orDash = true, style = headerButton() }) {
  const prusa = printer.connectionType === "prusalink";
  const url = prusa ? printer.prusalinkUrl : printer.mainsailUrl;
  const name = prusa ? "PrusaLink" : "Mainsail";
  if (!url) return orDash ? <span style={monoText(12, c.textFaint)}>—</span> : null;
  return (
    <a
      data-testid={prusa ? "printer-open-prusalink" : "printer-open-mainsail"} href={url} target="_blank" rel="noreferrer"
      onClick={(e) => e.stopPropagation()} // not also opening the printer's page here
      title={`Open ${printer.name}'s ${name} in a new tab (${url})`} style={{ ...style, display: "inline-flex", textDecoration: "none" }}
    >
      <ExternalLink size={12} />
      {name}
    </a>
  );
}

// A column heading that sorts the list by it: its arrow shows which way, or that it can (when another column is used)
function SortHeading({ id, sort, onSort }) {
  const label = SORTS[id];
  const on = sort.key === id;
  const words = id === "name" || id === "kind" ? ["A→Z", "Z→A"] : ["low to high", "high to low"];
  const now = on ? (sort.dir === "asc" ? words[0] : words[1]) : null;
  return (
    <button
      data-testid={`printer-sort-${id}`}
      onClick={() => onSort(id)}
      title={on ? `Sorted ${now}. Click to reverse` : `Sort by ${label.toLowerCase().replace("ip", "IP")}`}
      aria-label={on ? `${label}, sorted ${now}. Click to reverse` : `Sort by ${label}`}
      style={{
        display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", padding: 0, cursor: "pointer",
        color: on ? c.textMuted : c.textFaint, ...ui, fontSize: fs(12), justifySelf: "start",
      }}
    >
      {label}
      {!on ? <ArrowUpDown size={12} style={{ opacity: 0.6 }} /> : sort.dir === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
    </button>
  );
}
