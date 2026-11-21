import { c, fs, ui } from "../theme.js";
import { uiText } from "../styles.js";

// The Camera switch on a printer's form: which of its IPs its cameras are reached at, by Monitor, Stream control and
// the YouTube and Twitch streams alike. Wired on the left, Wireless on the right; a side whose IP isn't filled in is
// greyed out and can't be chosen. `value`: the choice ("wired" | "wireless"), or null: not chosen, shown on Wired (or
// on the one IP there), and its cameras then follow whichever IP the printer answers at.

// what the switch shows: the choice when its IP is there, else Wired when it's there, else Wireless; null: no IP
export const shownNetwork = (value, wiredIp, wirelessIp) => {
  const have = { wired: !!wiredIp, wireless: !!wirelessIp };
  return [value, "wired", "wireless"].find((n) => n && have[n]) || null;
};
// what's saved: the choice, or "" (the default) when its IP has gone
export const savedNetwork = (value, wiredIp, wirelessIp) => (value && (value === "wired" ? wiredIp : wirelessIp) ? value : "");

export function CameraNetworkSwitch({ value, onChange, wiredIp, wirelessIp }) {
  const have = { wired: !!wiredIp, wireless: !!wirelessIp };
  const shown = shownNetwork(value, wiredIp, wirelessIp);
  const side = (network, label, ip) => {
    const on = shown === network;
    const can = have[network];
    return (
      <button
        type="button" data-testid={`camera-network-${network}`} role="radio" aria-checked={on} disabled={!can}
        onClick={() => can && onChange(network)}
        title={can ? `Reach its cameras at its ${label.toLowerCase()} IP, ${ip}` : `No ${label.toLowerCase()} IP: add one above to choose it`}
        style={{
          flex: 1, padding: "6px 10px", border: "none", borderRadius: 999, cursor: can ? "pointer" : "not-allowed",
          background: on ? c.amber : "transparent", color: on ? c.bg : can ? c.textMuted : c.textFaint,
          opacity: can ? 1 : 0.45, fontWeight: on ? 600 : 400, ...ui, fontSize: fs(13), transition: "background 120ms",
        }}
      >
        {label}
      </button>
    );
  };
  return (
    <div data-testid="camera-network" style={{ marginBottom: 14 }}>
      <div style={uiText(12, c.textFaint, { marginBottom: 5 })}>Camera</div>
      <div role="radiogroup" aria-label="Camera network" style={{ display: "flex", gap: 2, padding: 2, maxWidth: 260, border: `1px solid ${c.border}`, borderRadius: 999 }}>
        {side("wired", "Wired", wiredIp)}
        {side("wireless", "Wireless", wirelessIp)}
      </div>
      <div style={uiText(11, c.textFaint, { marginTop: 5, lineHeight: 1.5 })}>
        {!shown
          ? "Add the printer's wired or wireless IP above to choose where its camera is reached."
          : value && have[value]
            ? `Monitor, Stream control and the YouTube and Twitch streams reach its camera at ${shown === "wired" ? wiredIp : wirelessIp}.`
            : have.wired && have.wireless
              ? `Its camera is reached at ${wiredIp}, or ${wirelessIp} while the cable is out. Choose one to keep it there.`
              : `Its camera is reached at ${wiredIp || wirelessIp}.`}
      </div>
    </div>
  );
}
