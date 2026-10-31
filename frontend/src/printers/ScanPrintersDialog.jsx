import { useEffect, useRef, useState } from "react";
import { HelpCircle, Loader2 } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { cancelButton, monoText, primaryButton, uiText } from "../styles.js";
import { createPrinter, discoverPrinters, errorText } from "../api.js";
import { useData } from "../data.jsx";

import { Badge, ProgressBar } from "../components/common/ui.jsx";
import { plural } from "../lib/format.js";

const CIDR_HELP =
  "A range of addresses, written as the first address / how many bits stay fixed. " +
  "192.168.1.0/24 means 192.168.1.1 to 192.168.1.254, the usual home or shop network. " +
  "Up to a /22 (1024 addresses) can be scanned at once.";

// The range to start with: the /24 that Farmhand itself is on, when the browser reached it by an IPv4 address
export function guessRange(host = window.location.hostname) {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.\d{1,3}$/.exec(host);
  return m && m[1] !== "127" ? `${m[1]}.${m[2]}.${m[3]}.0/24` : "";
}

// A name for each printer found: its hostname (its IP when it gave none). Where a hostname is shared, by printers
// found together or with one already in Farmhand, each of them gets its IP's last number added: "mainsailos-21".
export function suggestNames(found, existingNames) {
  const taken = new Set(existingNames);
  const count = {};
  for (const f of found) if (f.hostname) count[f.hostname] = (count[f.hostname] || 0) + 1;
  return Object.fromEntries(
    found.map((f) => {
      if (!f.hostname) return [f.ip, f.ip];
      const clash = count[f.hostname] > 1 || taken.has(f.hostname);
      return [f.ip, clash ? `${f.hostname}-${f.ip.split(".").pop()}` : f.hostname];
    }),
  );
}

const Actions = ({ children }) => <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>{children}</div>;

// Scan a network range for printers that aren't in Farmhand yet, and add the ones picked. Only Cancel (or the ✕)
// closes it: clicking beside it does nothing, so a scan or a half-made choice isn't lost by a stray click.
export function ScanPrintersDialog({ onClose }) {
  const { printers, putPrinter } = useData();
  const [phase, setPhase] = useState("enter"); // enter | scanning | results | adding | done | error
  const [cidr, setCidr] = useState(guessRange);
  const [scannedRange, setScannedRange] = useState("");
  const [found, setFound] = useState([]);
  const [selected, setSelected] = useState({}); // ip -> chosen?
  const [names, setNames] = useState({}); // ip -> the name it'll be added as
  const [progress, setProgress] = useState(0);
  const [summary, setSummary] = useState(null); // { added, failed: [{name, error}] }
  const [error, setError] = useState(null);
  const scanning = useRef(null); // the scan's AbortController
  const stopped = useRef(false); // Cancel was pressed while adding

  // Leaving (Cancel, ✕) stops waiting for a scan, whose answer the server still finishes and is dropped, and stops
  // adding after the printer being added now
  useEffect(
    () => () => {
      scanning.current?.abort();
      stopped.current = true;
    },
    [],
  );
  const cancel = onClose;

  const startScan = async () => {
    const range = cidr.trim();
    if (!range) return;
    const controller = new AbortController();
    scanning.current = controller;
    setScannedRange(range);
    setPhase("scanning");
    try {
      const result = await discoverPrinters(range, { signal: controller.signal });
      setFound(result);
      setSelected(Object.fromEntries(result.map((f) => [f.ip, true]))); // everything found, ticked
      setNames(suggestNames(result, printers.map((p) => p.name)));
      setPhase("results");
    } catch (e) {
      if (e.name === "AbortError") return; // cancelled: the dialog is already gone
      setError(errorText(e));
      setPhase("error");
    }
  };

  const chosen = found.filter((f) => selected[f.ip]);
  const allChosen = found.length > 0 && chosen.length === found.length;
  // A name that's blank, already a printer's, or given to two of the chosen ones can't be added
  const existing = new Set(printers.map((p) => p.name));
  const nameProblem = (f) => {
    const name = (names[f.ip] || "").trim();
    if (!name) return "needs a name";
    if (existing.has(name)) return "a printer has this name";
    if (chosen.filter((o) => (names[o.ip] || "").trim() === name).length > 1) return "same name twice";
    return null;
  };
  const blocked = chosen.length === 0 || chosen.some(nameProblem);

  const addChosen = async () => {
    setProgress(0);
    setPhase("adding");
    let added = 0;
    const failed = [];
    for (const [i, f] of chosen.entries()) {
      if (stopped.current) return;
      const name = names[f.ip].trim();
      try {
        // Its own IPs when it said which is which; otherwise the address it answered on, as its wired IP
        const ips = f.wiredIp || f.wirelessIp ? { wiredIp: f.wiredIp, wirelessIp: f.wirelessIp } : { wiredIp: f.ip };
        putPrinter(await createPrinter({ name, kind: f.firmware || "", ...ips, connectionType: f.connectionType }));
        added += 1;
      } catch (e) {
        failed.push({ name, error: errorText(e) });
      }
      setProgress(i + 1);
    }
    setSummary({ added, failed });
    setPhase("done");
  };

  const cancelBtn = (label = "Cancel") => (
    <button type="button" onClick={cancel} style={cancelButton()}>
      {label}
    </button>
  );

  if (phase === "enter") {
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          startScan();
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
          onChange={(e) => setCidr(e.target.value)}
          placeholder="e.g. 192.168.1.0/24"
          autoComplete="off"
          style={{ width: "100%", background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, color: c.textPrimary, padding: "8px 10px", fontSize: fs(13), ...ui }}
        />
        <div style={uiText(11, c.textFaint, { marginTop: 8, lineHeight: 1.5 })}>
          Farmhand asks every address in the range whether a Klipper or Kalico printer (Mainsail, Fluidd) answers there.
          Printers already in Farmhand are skipped. Nothing is added until you pick from what's found.
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
  if (phase === "scanning") {
    return (
      <div data-testid="scan-spinner">
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "18px 4px" }}>
          <Loader2 size={18} color={c.amber} style={{ animation: "fh-spin 1s linear infinite", flexShrink: 0 }} />
          <div style={uiText(13, c.textMuted)}>
            Looking for printers in <span style={monoText(13, c.heading)}>{scannedRange}</span>… this takes a few seconds.
          </div>
        </div>
        <Actions>{cancelBtn()}</Actions>
      </div>
    );
  }
  if (phase === "error") {
    return (
      <>
        <div style={uiText(13, c.amber, { lineHeight: 1.6 })}>{error}</div>
        <Actions>
          {cancelBtn()}
          <button onClick={() => setPhase("enter")} style={primaryButton()}>
            Change the range
          </button>
        </Actions>
      </>
    );
  }
  if (phase === "adding") {
    return (
      <div>
        <div style={uiText(13, c.textMuted, { marginBottom: 10 })}>
          Adding {Math.min(progress + 1, chosen.length)} of {chosen.length}…
        </div>
        <ProgressBar pct={chosen.length ? Math.round((progress / chosen.length) * 100) : 0} smooth />
        <Actions>{cancelBtn("Stop")}</Actions>
      </div>
    );
  }
  if (phase === "done") {
    return (
      <div data-testid="scan-summary">
        <div style={uiText(14, c.heading, { marginBottom: 8 })}>Added {plural(summary.added, "printer", "printers")}.</div>
        {summary.added > 0 && (
          <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 8 })}>
            Each one's wired and Wi-Fi IPs went in as it reported them (the address it answered on counts as wired when it didn't say). Rename them to match your slicer's printer profiles, and add an API key to any marked as needing one, on the printer's own page.
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

  // results
  if (found.length === 0) {
    return (
      <>
        <div data-testid="scan-none" style={uiText(13, c.textMuted, { lineHeight: 1.6 })}>
          No new printers found in <span style={monoText(13, c.heading)}>{scannedRange}</span>. Any printers in that range are already in Farmhand, or
          they're switched off.
        </div>
        <Actions>
          {cancelBtn()}
          <button onClick={() => setPhase("enter")} style={primaryButton()}>
            Scan another range
          </button>
        </Actions>
      </>
    );
  }
  const cols = "28px 1fr 150px 110px";
  const head = uiText(12, c.textFaint);
  return (
    <div data-testid="scan-results">
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 10 })}>
        Found <b style={{ color: c.heading }}>{plural(found.length, "new printer", "new printers")}</b> in{" "}
        <span style={monoText(13, c.heading)}>{scannedRange}</span>. Each is added under the name shown, which you can change here or later.
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
                aria-label={`Add ${names[f.ip]}`}
                checked={!!selected[f.ip]}
                onChange={(e) => setSelected((prev) => ({ ...prev, [f.ip]: e.target.checked }))}
                style={{ accentColor: c.amber }}
              />
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
                <span style={uiText(12, c.textMuted)}>{f.firmware || "Unknown"}</span>
                {f.needsApiKey && <Badge tone="amber">needs API key</Badge>}
              </div>
            </div>
          );
        })}
      </div>
      <Actions>
        {cancelBtn()}
        <button data-testid="scan-add" onClick={addChosen} disabled={blocked} style={primaryButton(blocked)}>
          Add {plural(chosen.length, "printer", "printers")}
        </button>
      </Actions>
    </div>
  );
}
