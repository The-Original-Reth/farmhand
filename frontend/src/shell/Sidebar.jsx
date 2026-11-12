import { useState } from "react";
import { Archive, Bell, Camera, LineChart, LayoutDashboard, Puzzle, Video, Youtube } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { monoText, uiText } from "../styles.js";
import { API_BASE } from "../api.js";
import { SECTIONS, pluginSection } from "./useNavigation.js";

// `npm run mock`: the real UI on built-in sample data (frontend/mock/). Said plainly in the sidebar, so the mockup
// is never mistaken for the real farm, with a way back to the untouched sample data.
const MOCKUP = !!import.meta.env.VITE_MOCK;
function MockupBadge() {
  const [busy, setBusy] = useState(false);
  return (
    <div data-testid="mockup-badge" style={{ margin: "14px 4px 0", border: `1px dashed ${c.amber}`, borderRadius: 4, padding: "10px 12px", background: c.amberDim }}>
      <div style={{ ...ui, fontSize: fs(12), fontWeight: 600, color: c.amber, marginBottom: 4 }}>Mockup</div>
      <div style={uiText(11, c.textMuted, { lineHeight: 1.5, marginBottom: 8 })}>
        Sample data, no real farm. Changes last until the mockup restarts.
      </div>
      <button
        data-testid="mockup-reset"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await fetch(`${API_BASE}/__reset`, { method: "POST" });
          window.location.reload();
        }}
        style={{ ...ui, fontSize: fs(11), background: "none", color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 3, padding: "3px 8px", cursor: busy ? "default" : "pointer" }}
      >
        {busy ? "Resetting…" : "Reset sample data"}
      </button>
    </div>
  );
}

// Each section has an address of its own (/printers, /monitor…), so a menu item is a link: Ctrl-click, middle-click
// or "Open in new tab" opens that section in another tab, and a plain click changes section here (onOpen).
function NavItem({ section: { key, label, Icon }, current, count, onOpen }) {
  const here = current === key;
  return (
    <a
      href={`/${key}`}
      onClick={(e) => {
        if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return; // the browser opens a new tab
        e.preventDefault();
        onOpen(key);
      }}
      style={{
        boxSizing: "border-box",
        textDecoration: "none",
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "9px 14px",
        borderRadius: 4,
        border: "none",
        background: here ? c.panelAlt : "transparent",
        color: here ? c.textPrimary : c.textMuted,
        cursor: "pointer",
        ...ui,
        fontSize: fs(14),
        textAlign: "left",
        marginBottom: 2,
      }}
    >
      <Icon size={16} color={here ? c.amber : c.textFaint} />
      <span style={{ flex: 1 }}>{label}</span>
      <span style={monoText(11, c.textFaint)}>{count ?? ""}</span>
    </a>
  );
}

const DONATE_URL = "https://www.3dprintingelves.org/donate-now";
const DONATE_TITLE = "Donate to 3D Printing Elves (opens their donation page in a new tab)";

// At the foot of the menu: the 3D Printing Elves logo (frontend/public), their donation page in a new tab when
// clicked, and after the thanks the Voron heart, Voron Design's site in a new tab
function Thanks() {
  return (
    <div style={{ marginTop: "auto", padding: "16px 14px 0", flexShrink: 0 }}>
      <a href={DONATE_URL} target="_blank" rel="noreferrer" data-testid="elves-logo" title={DONATE_TITLE} style={{ display: "block", width: 150, textDecoration: "none" }}>
        <img src="/3d-printing-elves.webp" alt="3D Printing Elves" width={150} height={110} style={{ display: "block", width: 150, height: "auto" }} />
      </a>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 4, width: 150, marginTop: 6, whiteSpace: "nowrap" }}>
        <a
          href={DONATE_URL}
          target="_blank"
          rel="noreferrer"
          data-testid="elves-thanks"
          title={DONATE_TITLE}
          style={{ fontSize: fs(11), color: c.textMuted, lineHeight: 1.5, textDecoration: "none" }}
        >
          Your support is appreciated
        </a>
        {/* the Voron heart (frontend/public, from VoronDesign/Voron-Extras Images/Logo/SVG/Heart_Logo.svg) */}
        <a href="https://vorondesign.com/" target="_blank" rel="noreferrer" data-testid="voron-heart" title="Voron Design (opens in a new tab)" style={{ display: "block", flexShrink: 0 }}>
          <img src="/voron-heart.svg" alt="Voron Design" width={14} height={12} style={{ display: "block", width: 14, height: "auto" }} />
        </a>
      </div>
    </div>
  );
}

// The icon a plugin's manifest names for its menu entry ("video"...), from the few Farmhand knows; a puzzle piece otherwise
const PLUGIN_ICONS = { youtube: Youtube, video: Video, camera: Camera, chart: LineChart, bell: Bell, dashboard: LayoutDashboard };

// Plugins that take a slot of their own in the main menu instead of the plugins group below it: plugin id -> the section
// it comes after, and its icon. Stream was Farmhand's own page, after Monitor, until it became a plugin (YouTube Stream); it
// keeps its place, under the menu name its manifest gives (YouTube).
const MAIN_MENU_SLOTS = { stream: { after: "monitor", Icon: Youtube } };

const pluginItem = (p) => ({ key: pluginSection(p.id), label: p.page.menu, Icon: MAIN_MENU_SLOTS[p.id]?.Icon || PLUGIN_ICONS[p.page.icon] || Puzzle });

// The menu down the left: Farmhand's name, a link per section (with how many models and printers there are), a link
// per plugin page (`plugins`: the ones switched on with a page; those in MAIN_MENU_SLOTS among the sections, the rest
// after them), and the thanks at the foot. `counts`: section key -> the number shown beside it.
export function Sidebar({ current, counts, plugins = [], onOpen }) {
  const slotted = plugins.filter((p) => MAIN_MENU_SLOTS[p.id]);
  const others = plugins.filter((p) => !MAIN_MENU_SLOTS[p.id]);
  const main = SECTIONS.flatMap((s) => [s, ...slotted.filter((p) => MAIN_MENU_SLOTS[p.id].after === s.key).map(pluginItem)]);
  return (
    <div
      style={{
        width: 220,
        borderRight: `1px solid ${c.border}`,
        background: c.panel,
        padding: 16,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        overflowY: "auto", // a window too short for all of it scrolls the menu, rather than covering anything
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 24, padding: "0 4px" }}>
        <Archive size={18} color={c.amber} />
        <span style={{ fontSize: fs(15), fontWeight: 600, letterSpacing: 0.2, color: c.heading }}>Farmhand</span>
      </div>
      {main.map((s) => (
        <NavItem key={s.key} section={s} current={current} count={counts[s.key]} onOpen={onOpen} />
      ))}
      {others.length > 0 && (
        <div data-testid="plugin-menu" style={{ borderTop: `1px solid ${c.border}`, marginTop: 10, paddingTop: 10 }}>
          {others.map((p) => (
            <NavItem key={p.id} section={pluginItem(p)} current={current} onOpen={onOpen} />
          ))}
        </div>
      )}
      <div style={{ borderTop: `1px solid ${c.border}`, marginTop: 12, paddingTop: 12 }}>
        <div style={{ fontSize: fs(11), color: c.textFaint, padding: "0 14px", lineHeight: 1.6 }}>
          An archive: nothing here re-slices, and a print only goes to a printer when you send it.
        </div>
      </div>
      {MOCKUP && <MockupBadge />}
      <Thanks />
    </div>
  );
}
