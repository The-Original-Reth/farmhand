import { c } from "../theme.js";
import { fieldBox, panelBox, uiText } from "../styles.js";

// The Stream page's own look, so its panels and the square editor's fields look alike.

export const panel = () => panelBox({ padding: 16, display: "flex", flexDirection: "column", gap: 12 });
export const heading = uiText(14, c.heading, { fontWeight: 600 });
export const subheading = uiText(13, c.heading, { fontWeight: 600 });

export const help = uiText(12, c.textFaint, { lineHeight: 1.5 });
export const box = () => ({ ...fieldBox(), padding: "5px 8px" });
export const label12 = uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6 });
export const colourBox = { width: 30, height: 22, padding: 0, border: `1px solid ${c.border}`, background: "none", cursor: "pointer" };
