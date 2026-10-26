// Styles used in many places. They're functions, not objects: the theme changes in place when the look is changed
// (theme.js), so a style has to be worked out each time it's drawn.
import { c, fs, mono, ui } from "./theme.js";

// Text in the interface font: uiText(13, c.textFaint) or with more, uiText(12, c.textMuted, { marginBottom: 8 })
export const uiText = (size, color, extra) => ({ ...ui, fontSize: fs(size), color, ...extra });
export const monoText = (size, color, extra) => ({ ...mono, fontSize: fs(size), color, ...extra });

// The small outlined buttons in a section's heading row ("Sync now", "Add maintenance"...)
export const headerButton = () => ({
  display: "flex", alignItems: "center", gap: 5, ...ui, fontSize: fs(12), background: "none", color: c.textMuted,
  border: `1px solid ${c.border}`, borderRadius: 3, padding: "0 9px", height: 26, cursor: "pointer", flexShrink: 0,
  textDecoration: "none", boxSizing: "border-box",
});

// An outlined button with an icon and a label, as on the page toolbars: small (12) or regular (13)
export const toolButton = (size = 12, extra) => ({
  display: "flex", alignItems: "center", gap: 6, ...ui, fontSize: fs(size), background: "none", color: c.textMuted,
  border: `1px solid ${c.border}`, borderRadius: 4, padding: size === 13 ? "7px 12px" : "5px 10px", cursor: "pointer", ...extra,
});

// A dialog's buttons: Cancel, and the amber one that does it (dimmed while it can't)
export const cancelButton = (busy = false) => ({
  ...ui, fontSize: fs(13), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3,
  padding: "7px 14px", cursor: busy ? "default" : "pointer",
});
export const primaryButton = (disabled = false) => ({
  ...ui, fontSize: fs(13), background: c.amber, color: c.onAccent, border: "none", borderRadius: 3, padding: "7px 14px",
  fontWeight: 600, cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.7 : 1,
});

// Amber underlined text that acts as a button ("Clear search")
export const linkButton = (size = 13) => ({
  ...ui, fontSize: fs(size), background: "none", border: "none", color: c.amber, textDecoration: "underline", cursor: "pointer", padding: 0,
});
