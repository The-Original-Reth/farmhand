import { useEffect, useMemo, useState } from "react";
import { Cable, FileBox, Lock, Pencil, Printer, Trash2, Wifi } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { linkButton, monoText, toolButton, uiText } from "../styles.js";
import { deletePrinter, renameBundle } from "../api.js";
import { useData } from "../data.jsx";

import { EditableName } from "../bundles/EditableName.jsx";
import { BundleCard } from "../bundles/BundleCard.jsx";
import { newestFirst, useBundleExpansion, VersionsToggleAll } from "../bundles/versions.jsx";
import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { SearchBox } from "../components/common/fields.jsx";
import { Badge, SectionLabel, SectionToggle } from "../components/common/ui.jsx";
import { Highlighted, searchWords } from "../lib/search.jsx";
import { readStoredObject, writeStored } from "../lib/storage.js";
import { NotesSection } from "../notes/NotesSection.jsx";
import { EnergyPanel } from "./EnergyPanel.jsx";
import { MaintenanceSection } from "./Maintenance.jsx";
import { MoonrakerCard, useMoonraker } from "./Moonraker.jsx";
import { PrintHistory } from "./PrintHistory.jsx";
import { EditPrinterForm } from "./PrinterForms.jsx";
import { PrusaLinkCard, usePrusaLink } from "./PrusaLink.jsx";
import { SubPrinters, usesSubPrinter } from "./SubPrinters.jsx";

// Searching the 3MF files on one printer: like the Models search, every word has to be found, in any of the file's
// names (every version), the sub printers they were sliced with, the models it was sliced from, its slicer, or its notes.
function bundleMatches(bundle, models, words, subPrinters) {
  if (words.length === 0) return true;
  const haystack = [
    ...bundle.versions.map((v) => v.filename || ""),
    ...bundle.versions.map((v) => subPrinters.find((s) => s.id === v.subPrinterId)?.name || ""),
    ...models.map((m) => m.name),
    bundle.slicer || "",
    bundle.notes || "",
  ].join("\n").toLowerCase();
  return words.every((w) => haystack.includes(w));
}

// Which parts of a printer page are folded away: { moonraker, threemf, history, and inside Moonraker/PrusaLink:
// connection, energy, maintenance } (true = folded). The same on every printer, remembered in this browser. The page's
// own sections start folded until opened; the ones inside Moonraker start open.
// (The key changed when "folded" became the start, so sections left open under the old default start folded again.)
const PRINTER_SECTIONS_KEY = "farmhand.printerSections.v2";
const OPEN_AT_START = new Set(["connection", "energy", "maintenance"]);
function usePrinterSections() {
  const [folded, setFolded] = useState(() => readStoredObject(PRINTER_SECTIONS_KEY));
  const isFolded = (state, name) => state[name] ?? !OPEN_AT_START.has(name);
  const toggle = (name) =>
    setFolded((prev) => {
      const next = { ...prev, [name]: !isFolded(prev, name) };
      writeStored(PRINTER_SECTIONS_KEY, next);
      return next;
    });
  return { isOpen: (name) => !isFolded(folded, name), toggle };
}

// The printer's Moonraker or PrusaLink (whichever it uses), looked at every few seconds while the page is open, with
// everything that follows it: its status card, energy and maintenance, and the print history. Kept apart from the rest
// of the page so a look redraws only these: `children` (the 3MF files, which sit between them on the page) is made by
// the page and doesn't change when a look comes in, so React leaves it alone. Starts over if the address or login
// changes.
function PrinterLive({ printer, sections, refreshPrinters, children }) {
  const [maintenanceDue, setMaintenanceDue] = useState(0); // reported by the maintenance list, for when it's folded
  const isPrusaLink = printer.connectionType === "prusalink";
  const mr = useMoonraker(
    isPrusaLink ? null : printer.id,
    isPrusaLink ? null : `${printer.id}|${printer.moonrakerUrl}|${printer.hasMoonrakerApiKey}`,
    refreshPrinters, // a sync moves the printer's print hours and service on; its models and 3MFs are unchanged
  );
  const pl = usePrusaLink(
    isPrusaLink ? printer.id : null,
    isPrusaLink ? `${printer.id}|${printer.prusalinkUrl}|${printer.prusalinkUsername}|${printer.hasPrusalinkPassword}` : null,
    refreshPrinters,
  );
  const link = isPrusaLink ? pl : mr; // for what both show: the connection dot, the history reloading
  const fold = (name) => ({ open: sections.isOpen(name), onToggle: () => sections.toggle(name) }); // a section inside it

  return (
    <>
      {/* Everything from the printer's Moonraker, foldable as one. Folded, it stays mounted (just hidden), so it
          keeps what it loaded and can still say if maintenance is due. */}
      <div data-testid="moonraker-group">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: sections.isOpen("moonraker") ? 14 : 0, flexWrap: "wrap" }}>
          <SectionToggle open={sections.isOpen("moonraker")} onToggle={() => sections.toggle("moonraker")} controlsId="moonraker-body" testId="toggle-moonraker">
            {isPrusaLink ? "PrusaLink: live status, printing and maintenance" : "Moonraker: connection, energy and maintenance"}
          </SectionToggle>
          {!sections.isOpen("moonraker") && (
            <>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(12), color: c.textFaint }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: !link.status ? c.textFaint : link.status.reachable ? c.green : c.danger }} />
                {!link.status ? "checking…" : !link.status.reachable ? "not reachable" : (link.status.job || link.status.print) ? `printing · ${Math.round((link.status.job || link.status.print).progress || 0)}%` : "connected"}
              </span>
              {maintenanceDue > 0 && <Badge tone="danger">{maintenanceDue} maintenance due</Badge>}
            </>
          )}
        </div>
        <div id="moonraker-body" style={{ display: sections.isOpen("moonraker") ? "flex" : "none", flexDirection: "column", gap: 28 }}>
          {isPrusaLink ? (
            <>
              <PrusaLinkCard printer={printer} pl={pl} {...fold("connection")} />
              <MaintenanceSection printer={printer} reachable onDueCount={setMaintenanceDue} {...fold("maintenance")} />
            </>
          ) : (
            <>
              <MoonrakerCard printer={printer} mr={mr} {...fold("connection")} />
              <EnergyPanel printer={printer} syncTick={mr.syncTick} {...fold("energy")} />
              <MaintenanceSection printer={printer} reachable={!!mr.status?.reachable} onDueCount={setMaintenanceDue} {...fold("maintenance")} />
            </>
          )}
        </div>
      </div>

      {children}

      <PrintHistory printer={printer} syncTick={link.syncTick} open={sections.isOpen("history")} onToggle={() => sections.toggle("history")} />
    </>
  );
}

// One printer: its 3MF search, details and notes, Moonraker or PrusaLink with maintenance, its 3MF files and history
export function PrinterPage({ printerId, compareSelection, toggleCompareSelect, onDeleted }) {
  const { printers, bundlesForPrinter, modelsForPrinter, versionsByBundle, modelsForBundle, refreshPrinters, putBundle } = useData();
  const expansion = useBundleExpansion();
  const [editPrinterOpen, setEditPrinterOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [query, setQuery] = useState(""); // the search for this printer's 3MF files
  const [subFilter, setSubFilter] = useState(null); // only the 3MFs sliced with this sub printer (its id); null = all

  useEffect(() => {
    setQuery(""); // a fresh search, and every 3MF, for each printer
    setSubFilter(null);
  }, [printerId]);

  const sections = usePrinterSections();
  const printer = printers.find((p) => p.id === printerId);

  const allBundles = useMemo(() => [...bundlesForPrinter(printer.id)].sort(newestFirst), [bundlesForPrinter, printer.id]);
  const words = useMemo(() => searchWords(query), [query]);
  const searching = words.length > 0;
  const filterSub = printer.subPrinters.find((s) => s.id === subFilter) || null; // gone if it was removed
  const pBundles = useMemo(
    () =>
      allBundles.filter(
        (b) => (!filterSub || usesSubPrinter(b, filterSub.id)) && bundleMatches(b, modelsForBundle(b), words, printer.subPrinters),
      ),
    [allBundles, modelsForBundle, words, filterSub, printer.subPrinters],
  );
  const modelCount = modelsForPrinter(printer.id).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
      {editPrinterOpen && (
        <Modal title="Edit printer" onClose={() => setEditPrinterOpen(false)}>
          <EditPrinterForm printer={printer} onClose={() => setEditPrinterOpen(false)} />
        </Modal>
      )}
      {deleteOpen && (
        <ConfirmDialog
          title="Delete printer"
          confirmLabel="Delete printer"
          onClose={() => setDeleteOpen(false)}
          onConfirm={async () => {
            await deletePrinter(printer.id);
            onDeleted(); // off its page before it's gone from the list
            await refreshPrinters();
          }}
        >
          Delete <b style={{ color: c.heading }}>{printer.name}</b> from Farmhand for good? Its print history, notes, sub
          printers, parts and maintenance go with it. This can't be undone.
        </ConfirmDialog>
      )}
      {/* searches this printer's 3MF files (listed further down); at the top so it's the first thing to hand */}
      {allBundles.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <SearchBox
            value={query}
            onChange={setQuery}
            testId="printer-3mf-search"
            clearTestId="printer-3mf-search-clear"
            placeholder={`Search 3MF files on ${printer.name}…`}
            label={`Search 3MF files on ${printer.name}`}
            style={{ flex: "1 1 320px", maxWidth: 460 }}
          />
          {(searching || filterSub) && (
            <span data-testid="printer-3mf-count" style={uiText(12, c.textFaint)}>
              {pBundles.length} of {allBundles.length} 3MF files
            </span>
          )}
        </div>
      )}
      <div>
        <SectionLabel>Printer</SectionLabel>
        <div
          style={{
            border: `1px solid ${c.border}`,
            borderRadius: 4,
            padding: 14,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            background: c.panel,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: 4,
                border: `1px solid ${c.border}`,
                background: c.panelAlt,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Printer size={26} color={c.teal} strokeWidth={1.4} />
            </div>
            <div>
              <div style={uiText(15, c.heading, { display: "flex", alignItems: "center", gap: 8 })}>
                {printer.name}
                {allBundles.length > 0 && <Lock size={13} color={c.textFaint} />}
              </div>
              <div style={uiText(13, c.textMuted, { marginTop: 3 })}>{printer.kind}</div>
              <div style={{ display: "flex", gap: 14, marginTop: 8 }}>
                <div style={monoText(12, printer.wired ? c.textPrimary : c.textFaint, { display: "flex", alignItems: "center", gap: 5 })}>
                  <Cable size={12} color={printer.wired ? c.teal : c.textFaint} />
                  {printer.wired || "—"}
                </div>
                <div style={monoText(12, printer.wireless ? c.heading : c.textFaint, { display: "flex", alignItems: "center", gap: 5 })}>
                  <Wifi size={12} color={c.textFaint} />
                  {printer.wireless || "—"}
                </div>
              </div>
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5, alignItems: "flex-end", flexShrink: 0 }}>
            <button
              onClick={() => setEditPrinterOpen(true)}
              style={toolButton(12, { marginBottom: 3 })}
            >
              <Pencil size={12} />
              Edit
            </button>
            {printer.decommissioned && (
              <button
                data-testid="delete-printer"
                onClick={() => setDeleteOpen(true)}
                disabled={allBundles.length > 0}
                title={
                  allBundles.length > 0
                    ? `It still has ${allBundles.length} 3MF file${allBundles.length === 1 ? "" : "s"}. Delete ${allBundles.length === 1 ? "it" : "them"} first, then the printer can be deleted.`
                    : "Delete this decommissioned printer from Farmhand"
                }
                style={toolButton(12, { marginBottom: 3, color: c.danger, opacity: allBundles.length > 0 ? 0.5 : 1, cursor: allBundles.length > 0 ? "default" : "pointer" })}
              >
                <Trash2 size={12} />
                Delete
              </button>
            )}
            {printer.decommissioned ? <Badge>decommissioned</Badge> : <Badge tone="green">active</Badge>}
            <Badge tone="teal">{allBundles.length} 3MF</Badge>
            <Badge tone="teal">{modelCount} Models</Badge>
          </div>
        </div>
      </div>

      <SubPrinters
        printer={printer}
        bundles={allBundles}
        filter={filterSub?.id ?? null}
        onFilter={(id) => {
          setSubFilter(id);
          if (id != null && !sections.isOpen("threemf")) sections.toggle("threemf"); // so its 3MFs can be seen
        }}
      />

      <NotesSection key={printer.id} kind="printer" owner={printer} />

      <PrinterLive printer={printer} sections={sections} refreshPrinters={refreshPrinters}>
        <div data-testid="threemf-group">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: sections.isOpen("threemf") ? 10 : 0 }}>
            <SectionToggle open={sections.isOpen("threemf")} onToggle={() => sections.toggle("threemf")} controlsId="threemf-body" testId="toggle-threemf">
              3MF files on {printer.name}
              <span style={{ color: c.textFaint }}>({allBundles.length})</span>
            </SectionToggle>
            {sections.isOpen("threemf") && <VersionsToggleAll bundleList={pBundles} expansion={expansion} />}
          </div>
          {sections.isOpen("threemf") && (
          <div id="threemf-body">
          {filterSub && (
            <div data-testid="sub-printer-filter-note" style={uiText(13, c.textMuted, { padding: "0 4px 10px", lineHeight: 1.6 })}>
              Showing only the 3MF files sliced with <span style={monoText(12, c.heading)}>{filterSub.name}</span>.{" "}
              <button onClick={() => setSubFilter(null)} style={linkButton()}>
                Show all
              </button>
            </div>
          )}
          {searching && pBundles.length === 0 && (
            <div data-testid="printer-3mf-search-empty" style={uiText(13, c.textMuted, { padding: "12px 4px", lineHeight: 1.7 })}>
              No 3MF files on {printer.name} match <b style={{ color: c.heading }}>“{query.trim()}”</b>. Every word has to match a file name, a model, the slicer or the notes.{" "}
              <button
                onClick={() => setQuery("")}
                style={linkButton()}
              >
                Clear search
              </button>
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {pBundles.map((b) => (
              <BundleCard
                key={b.id}
                bundle={b}
                versions={versionsByBundle[b.id] || []}
                expansion={expansion}
                compareSelection={compareSelection}
                onToggleCompare={toggleCompareSelect}
                title={
                  <>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                      <FileBox size={15} color={c.textFaint} />
                      <EditableName
                        value={b.name}
                        label="this 3MF file" extension=".3mf" boxed
                        testId="bundle-name"
                        textStyle={{ ...mono, fontSize: fs(13) }}
                        onSave={async (name) => putBundle(await renameBundle(b, name))}
                      >
                        <span style={monoText(13, "inherit")}><Highlighted text={b.name} words={words} /></span>
                      </EditableName>
                      <Badge>{b.slicer}</Badge>
                    </div>
                    <div style={uiText(12, c.textFaint, { paddingLeft: 23 })}>
                      from <Highlighted text={modelsForBundle(b).map((m) => m.name).join(" + ")} words={words} />
                    </div>
                  </>
                }
              />
            ))}
          </div>
          </div>
          )}
        </div>

      </PrinterLive>
    </div>
  );
}
