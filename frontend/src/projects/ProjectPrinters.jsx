import { useState } from "react";
import { ExternalLink, Plus, Printer } from "lucide-react";
import { addProjectPrinter, removeProjectPrinter } from "../api.js";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { nameCollator } from "../models/modelSort.js";
import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { Row } from "../components/common/ui.jsx";
import { panelBox, primaryButton, toolButton, uiText } from "../styles.js";
import { WebUiButton } from "../printers/PrinterList.jsx";
import { plural } from "./ProjectFiles.jsx";

export function AddPrinterButton({ onClick }) {
  return (
    <button data-testid="printer-add" onClick={onClick} style={toolButton(12)}>
      <Plus size={12} />
      Add printer
    </button>
  );
}

// The printers a project uses: brought by its 3MFs (from Farmhand, or its own), or added by hand. Each says how many
// of the project's 3MFs are for it, opens its page, and can be removed from the project (the printer itself stays).
export function ProjectPrinters({ project, adding, onCloseAdd, onOpenPrinter }) {
  const { printers, bundles } = useData();
  const used = project.printerIds.map((id) => printers.find((p) => p.id === id)).filter(Boolean);
  const threemfsFor = (printerId) =>
    project.bundleIds.filter((id) => bundles.find((b) => b.id === id)?.printerId === printerId).length +
    project.threemfFiles.filter((f) => f.printerId === printerId).length;
  return (
    <>
      {used.length === 0 ? (
        <div style={panelBox({ padding: "7px 12px", ...uiText(13, c.textFaint, { lineHeight: 1.5 }) })}>
          No printers yet. A 3MF added to the project brings the printer it's for; <b style={{ color: c.textMuted }}>Add printer</b> adds one by hand.
        </div>
      ) : (
        <div style={panelBox({ overflow: "hidden" })}>
          {used.map((p) => (
            <PrinterRow key={p.id} project={project} printer={p} threemfs={threemfsFor(p.id)} onOpen={() => onOpenPrinter(p.id)} />
          ))}
        </div>
      )}
      {adding && <AddPrinters project={project} onClose={onCloseAdd} />}
    </>
  );
}

function PrinterRow({ project, printer: p, threemfs, onOpen }) {
  const { putProject } = useData();
  const [asking, setAsking] = useState(false);
  return (
    <div data-testid="project-printer" data-printer-id={p.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 8px 6px 12px", borderBottom: `1px solid ${c.border}`, flexWrap: "wrap" }}>
      <Printer size={15} color={c.textFaint} />
      <span style={uiText(13, c.heading, { fontWeight: 600 })}>{p.name}</span>
      <span style={uiText(12, c.textFaint, { flex: 1, minWidth: 0 })}>
        {[p.kind || (p.decommissioned ? "Decommissioned" : ""), plural(threemfs, "3MF file") + " in this project"].filter(Boolean).join(" · ")}
      </span>
      <button data-testid="printer-open" onClick={onOpen} title="Open its page" style={toolButton(12, { whiteSpace: "nowrap" })}>
        <ExternalLink size={12} />
        Open
      </button>
      {/* its own web page in a new tab: Mainsail for a Klipper printer, PrusaLink for a Prusa (nothing without an address) */}
      <WebUiButton printer={p} orDash={false} style={toolButton(12, { whiteSpace: "nowrap" })} />
      <button data-testid="printer-remove" onClick={() => setAsking(true)} title="Remove it from this project" style={toolButton(12, { whiteSpace: "nowrap" })}>
        Remove
      </button>
      {asking && (
        <ConfirmDialog
          title="Remove printer from project"
          confirmLabel="Yes, remove it"
          tone="warn"
          onClose={() => setAsking(false)}
          onConfirm={async () => putProject(await removeProjectPrinter(project.id, p.id))}
        >
          Are you sure you want to remove <strong>{p.name}</strong> from {project.name}? The printer itself, and the
          project's 3MF files for it, stay: nothing is deleted.
        </ConfirmDialog>
      )}
    </div>
  );
}

function AddPrinters({ project, onClose }) {
  const { printers, putProject } = useData();
  const { busy, error, run } = useAction();
  const choices = printers
    .filter((p) => !p.decommissioned && !project.printerIds.includes(p.id))
    .sort((a, b) => nameCollator.compare(a.name, b.name));
  return (
    <Modal title={`Add printers to ${project.name}`} onClose={onClose} width={480}>
      {error && <div style={uiText(12, c.amber, { marginBottom: 10 })}>{error}</div>}
      <div style={panelBox({ overflow: "hidden", maxHeight: "50vh", overflowY: "auto" })}>
        {choices.length === 0 ? (
          <div style={{ padding: 16, ...uiText(13, c.textFaint) }}>Every printer is in this project already.</div>
        ) : (
          choices.map((p) => (
            <Row key={p.id} hoverable={false}>
              <Printer size={15} color={c.textFaint} />
              <div style={{ flex: 1, minWidth: 0, marginLeft: 10 }}>
                <div style={uiText(13, c.textPrimary)}>{p.name}</div>
                {p.kind && <div style={uiText(12, c.textFaint, { marginTop: 2 })}>{p.kind}</div>}
              </div>
              <button
                disabled={busy}
                data-testid={`printer-pick-${p.id}`}
                onClick={() => run(async () => putProject(await addProjectPrinter(project.id, p.id)))}
                style={{ ...primaryButton(busy), fontSize: fs(12), padding: "5px 12px", marginLeft: 12, ...ui }}
              >
                Add
              </button>
            </Row>
          ))
        )}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
        <button onClick={onClose} style={toolButton(13)}>
          Done
        </button>
      </div>
    </Modal>
  );
}
