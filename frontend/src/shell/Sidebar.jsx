import { useState } from "react";
import { Archive, Bell, Camera, LineChart, LayoutDashboard, Puzzle, Radio, Twitch, Video, X, Youtube } from "lucide-react";
import { c, fixed, fs, ui } from "../theme.js";
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
const PLUGIN_ICONS = { youtube: Youtube, video: Video, camera: Camera, chart: LineChart, bell: Bell, dashboard: LayoutDashboard, twitch: Twitch };

// The streaming plugins, first in the plugins group in this order, each with its own icon: Stream control (built into
// Farmhand, there while it's switched on), YouTube Stream (stream) and Twitch Stream (twitch). Other plugins follow by name.
const STREAM_PLUGINS = { "stream-control": Radio, stream: Youtube, twitch: Twitch };
const STREAM_ORDER = Object.keys(STREAM_PLUGINS);
const rank = (p) => (p.id in STREAM_PLUGINS ? STREAM_ORDER.indexOf(p.id) : STREAM_ORDER.length);

const pluginItem = (p) => ({ key: pluginSection(p.id), label: p.page.menu, Icon: STREAM_PLUGINS[p.id] || PLUGIN_ICONS[p.page.icon] || Puzzle });

// The menu down the left: Farmhand's name, a link per section (with how many models and printers there are), a link
// per plugin page in the plugins group below them (`plugins`: the ones switched on with a page; the streaming ones
// first), and the thanks at the foot. `counts`: section key -> the number shown beside it.
// On a phone (`phone`) it's a drawer over the page instead: shown while `open`, and closed (onClose) by its ✕, a tap
// on the page beside it, or opening a section.
export function Sidebar({ current, counts, plugins = [], onOpen, phone = false, open = false, onClose }) {
  const others = [...plugins].sort((a, b) => rank(a) - rank(b) || a.page.menu.localeCompare(b.page.menu));
  const go = (key) => {
    onOpen(key);
    if (phone) onClose?.();
  };
  const menu = (
    <div
      data-testid="sidebar"
      aria-hidden={phone && !open ? true : undefined}
      style={{
        width: phone ? 260 : 220,
        maxWidth: "85vw",
        ...(phone && {
          position: "fixed", top: 0, bottom: 0, left: 0, zIndex: 60, transition: "transform 0.2s ease, visibility 0.2s",
          transform: open ? "none" : "translateX(-100%)", visibility: open ? "visible" : "hidden",
        }),
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
        <span style={{ fontSize: fs(15), fontWeight: 600, letterSpacing: 0.2, color: c.heading, flex: 1 }}>Farmhand</span>
        {phone && (
          <button
            type="button" data-testid="menu-close" onClick={onClose} aria-label="Close the menu"
            style={{ background: "none", border: "none", padding: 6, margin: -6, cursor: "pointer", display: "flex" }}
          >
            <X size={20} color={c.textMuted} />
          </button>
        )}
      </div>
      {SECTIONS.map((s) => (
        <NavItem key={s.key} section={s} current={current} count={counts[s.key]} onOpen={go} />
      ))}
      {others.length > 0 && (
        <div data-testid="plugin-menu" style={{ borderTop: `1px solid ${c.border}`, marginTop: 10, paddingTop: 10 }}>
          {others.map((p) => (
            <NavItem key={p.id} section={pluginItem(p)} current={current} onOpen={go} />
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
  if (!phone) return menu;
  return (
    <>
      {open && <div data-testid="menu-backdrop" onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 59, background: fixed.backdrop }} />}
      {menu}
    </>
  );
}
