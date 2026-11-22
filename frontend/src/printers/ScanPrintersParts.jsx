import { HelpCircle } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { monoText, primaryButton, uiText } from "../styles.js";
import { Badge } from "../components/common/ui.jsx";
import { plural } from "../lib/format.js";

// The steps of the Scan for printers dialog (ScanPrintersDialog.jsx), which keeps their state. `cancelBtn(label)` is
// its Cancel button.

const CIDR_HELP =
  "A range of addresses, written as the first address / how many bits stay fixed. " +
  "192.168.1.0/24 means 192.168.1.1 to 192.168.1.254, the usual home or shop network. " +
  "Up to a /22 (1024 addresses) can be scanned at once.";

export const Actions = ({ children }) => <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>{children}</div>;

// The range to scan
export function ScanRangeForm({ cidr, onCidr, onScan, cancelBtn }) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onScan();
      }}
    >
      <label htmlFor="scan-range" style={{ display: "flex", alignItems: "center", gap: 6, ...uiText(12, c.textFaint), marginBottom: 5 }}>
        Network range
        <span title={CIDR_HELP} style={{ display: "inline-flex", cursor: "help" }}>
          <HelpCircle size={13} aria-label={CIDR_HELP} />
        </span>
      </label>
      <input
        id="scan-range"
        data-testid="scan-range"
        autoFocus
        value={cidr}
        onChange={(e) => onCidr(e.target.value)}
        placeholder="e.g. 192.168.1.0/24"
        autoComplete="off"
        style={{ width: "100%", background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, padding: "8px 10px", fontSize: fs(13), ...ui }}
      />
      <div style={uiText(11, c.textFaint, { marginTop: 8, lineHeight: 1.5 })}>
        Farmhand asks every address in the range whether a Klipper or Kalico printer (Mainsail, Fluidd) or a Prusa (PrusaLink) answers there.
        Printers in use in Farmhand are skipped; a decommissioned one found again can be brought back. Nothing is added until you pick from what's found.
      </div>
      <Actions>
        {cancelBtn()}
        <button type="submit" data-testid="scan-start" disabled={!cidr.trim()} style={primaryButton(!cidr.trim())}>
          Scan
        </button>
      </Actions>
    </form>
  );
}

// What adding the chosen printers did
export function ScanSummary({ summary, cancelBtn }) {
  return (
    <div data-testid="scan-summary">
      <div style={uiText(14, c.heading, { marginBottom: 8 })}>
        {[
          (summary.added > 0 || !summary.back) && `Added ${plural(summary.added, "printer", "printers")}.`,
          summary.back > 0 && `Brought back ${plural(summary.back, "decommissioned printer", "decommissioned printers")}.`,
        ].filter(Boolean).join(" ")}
      </div>
      {summary.added > 0 && (
        <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 8 })}>
          Each one's wired and Wi-Fi IPs went in as it reported them (the address it answered on counts as wired when it didn't say). Rename them to match your slicer's printer profiles, and on the printer's own page (Edit) add the API key or PrusaLink password to any marked as needing one.
        </div>
      )}
      {summary.failed.length > 0 && (
        <div style={uiText(12, c.amber, { lineHeight: 1.6 })}>
          {plural(summary.failed.length, "printer couldn't be added", "printers couldn't be added")}:
          {summary.failed.map((f) => (
            <div key={f.name}>
              <b>{f.name}</b>: {f.error}
            </div>
          ))}
        </div>
      )}
      <Actions>{cancelBtn("Done")}</Actions>
    </div>
  );
}

// The printers found, each to tick and name
export function ScanResults({
  found, scannedRange, selected, setSelected, names, setNames, nameProblem, allChosen, chosen, chosenNew, blocked,
  addChosen, cancelBtn,
}) {
  const cols = "28px 1fr 150px 110px";
  const head = uiText(12, c.textFaint);
  return (
    <div data-testid="scan-results">
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 10 })}>
        Found <b style={{ color: c.heading }}>{plural(found.length, "printer", "printers")}</b> not in use in Farmhand in{" "}
        <span style={monoText(13, c.heading)}>{scannedRange}</span>. Each new one is added under the name shown, which you can change here or later.
        {found.some((f) => f.decommissionedId != null) && " A decommissioned one is brought back as it was, with its history and 3MF files."}
      </div>
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, maxHeight: 340, overflow: "auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: cols, alignItems: "center", gap: 8, padding: "8px 12px", background: c.panelAlt, borderBottom: `1px solid ${c.border}`, position: "sticky", top: 0 }}>
          <input
            type="checkbox"
            aria-label="Select all"
            checked={allChosen}
            onChange={(e) => setSelected(Object.fromEntries(found.map((f) => [f.ip, e.target.checked])))}
            style={{ accentColor: c.amber }}
          />
          <div style={head}>Hostname</div>
          <div style={head}>IP address</div>
          <div style={head}>Type</div>
        </div>
        {found.map((f, i) => {
          const problem = selected[f.ip] ? nameProblem(f) : null;
          return (
            <div
              key={f.ip}
              data-testid="scan-row"
              style={{ display: "grid", gridTemplateColumns: cols, alignItems: "center", gap: 8, padding: "6px 12px", borderTop: i === 0 ? "none" : `1px solid ${c.border}` }}
            >
              <input
                type="checkbox"
                aria-label={`Add ${f.decommissionedName ?? names[f.ip]}`}
                checked={!!selected[f.ip]}
                onChange={(e) => setSelected((prev) => ({ ...prev, [f.ip]: e.target.checked }))}
                style={{ accentColor: c.amber }}
              />
              {f.decommissionedId != null ? (
                <div style={{ minWidth: 0 }} data-testid="scan-row-decommissioned">
                  <div style={uiText(13, c.textPrimary, { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })} title={f.decommissionedName}>
                    {f.decommissionedName}
                  </div>
                  <div style={uiText(11, c.textFaint, { marginTop: 2 })}>Decommissioned: brings it back</div>
                </div>
              ) : (
              <div style={{ minWidth: 0 }}>
                <input
                  value={names[f.ip] || ""}
                  onChange={(e) => setNames((prev) => ({ ...prev, [f.ip]: e.target.value }))}
                  aria-label={`Name for ${f.ip}`}
                  title={f.hostname ? `Its hostname: ${f.hostname}` : "It didn't say its hostname"}
                  style={{ width: "100%", background: c.panelAlt, border: `1px solid ${problem ? c.danger : c.border}`, borderRadius: 3, color: c.textPrimary, padding: "4px 7px", fontSize: fs(13), ...ui }}
                />
                {problem && <div style={uiText(11, c.danger, { marginTop: 2 })}>{problem}</div>}
              </div>
              )}
              <div style={{ minWidth: 0 }}>
                <div style={monoText(12, c.textMuted)}>{f.ip}</div>
                {f.link && (
                  <div style={uiText(11, c.textFaint, { marginTop: 2 })}>
                    {f.link === "wired" ? "Wired" : "Wi-Fi"}
                    {f.link === "wired" && f.wirelessIp && ` · Wi-Fi ${f.wirelessIp}`}
                    {f.link === "wireless" && f.wiredIp && ` · wired ${f.wiredIp}`}
                  </div>
                )}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
                <span style={uiText(12, c.textMuted)}>{f.firmware || "Unknown"}{f.webUi ? ` · ${f.webUi}` : ""}</span>
                {f.needsApiKey && <Badge tone="amber">{f.connectionType === "prusalink" ? "needs password" : "needs API key"}</Badge>}
              </div>
            </div>
          );
        })}
      </div>
      <Actions>
        {cancelBtn()}
        <button data-testid="scan-add" onClick={addChosen} disabled={blocked} style={primaryButton(blocked)}>
          {[
            chosenNew > 0 && `Add ${plural(chosenNew, "printer", "printers")}`,
            chosen.length > chosenNew && `bring back ${chosen.length - chosenNew}`,
          ].filter(Boolean).join(", ").replace(/^b/, "B") || "Add printers"}
        </button>
      </Actions>
    </div>
  );
}
