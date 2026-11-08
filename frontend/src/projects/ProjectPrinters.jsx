import { ExternalLink, Plus, Printer } from "lucide-react";
import { addProjectPrinter, removeProjectPrinter } from "../api.js";
import { c } from "../theme.js";
import { useData } from "../data.jsx";
import { panelBox, toolButton, uiText } from "../styles.js";
import { WebUiButton } from "../printers/PrinterList.jsx";
import { EmptyBox, HeadingButton, PickDialog, TakeOutButton } from "./pieces.jsx";
import { plural } from "../lib/format.js";

export function AddPrinterButton({ onClick }) {
  return (
    <button data-testid="printer-add" onClick={onClick} style={toolButton(12)}>
      <Plus size={12} />
      Add printer
    </button>
  );
}

// The printers a project uses: brought by its 3MFs (from Farmhand, or its own), or added by hand. Each says how many
// of the project's 3MFs are for it, opens its page or its own web page, and can be removed from the project (the
// printer itself stays).
export function ProjectPrinters({ project, adding, onCloseAdd, onOpenPrinter }) {
  const { printers, bundles } = useData();
  const used = project.printerIds.map((id) => printers.find((p) => p.id === id)).filter(Boolean);
  const threemfsFor = (printerId) =>
    project.bundleIds.filter((id) => bundles.find((b) => b.id === id)?.printerId === printerId).length +
    project.threemfFiles.filter((f) => f.printerId === printerId).length;
  return (
    <>
      {used.length === 0 ? (
        <EmptyBox>
          No printers yet. A 3MF added to the project brings the printer it's for; <b style={{ color: c.textMuted }}>Add printer</b> adds one by hand.
        </EmptyBox>
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
  return (
    <div data-testid="project-printer" data-printer-id={p.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 8px 6px 12px", borderBottom: `1px solid ${c.border}`, flexWrap: "wrap" }}>
      <Printer size={15} color={c.textFaint} />
      <span style={uiText(13, c.heading, { fontWeight: 600 })}>{p.name}</span>
      <span style={uiText(12, c.textFaint, { flex: 1, minWidth: 0 })}>
        {[p.kind || (p.decommissioned ? "Decommissioned" : ""), plural(threemfs, "3MF file") + " in this project"].filter(Boolean).join(" · ")}
      </span>
      <HeadingButton testId="printer-open" Icon={ExternalLink} label="Open" title="Open its page" onClick={onOpen} />
      {/* its own web page in a new tab: Mainsail for a Klipper printer, PrusaLink for a Prusa (nothing without an address) */}
      <WebUiButton printer={p} orDash={false} style={toolButton(12, { whiteSpace: "nowrap" })} />
      <TakeOutButton
        testId="printer-remove"
        label="Remove"
        title="Remove it from this project"
        dialogTitle="Remove printer from project"
        confirmLabel="Yes, remove it"
        onConfirm={async () => putProject(await removeProjectPrinter(project.id, p.id))}
      >
        Are you sure you want to remove <strong>{p.name}</strong> from {project.name}? The printer itself, and the
        project's 3MF files for it, stay: nothing is deleted.
      </TakeOutButton>
    </div>
  );
}

// Picking printers to add by hand: every working printer not in the project yet
function AddPrinters({ project, onClose }) {
  const { printers } = useData();
  const items = printers
    .filter((p) => !p.decommissioned && !project.printerIds.includes(p.id))
    .map((p) => ({ id: p.id, name: p.name, sub: p.kind, Icon: Printer }));
  return (
    <PickDialog
      title={`Add printers to ${project.name}`}
      width={480}
      noun="printers"
      items={items}
      allTaken="Every printer is in this project already."
      add={(id) => addProjectPrinter(project.id, id)}
      pickTestId="printer-pick"
      onClose={onClose}
    />
  );
}
