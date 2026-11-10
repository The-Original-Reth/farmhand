import { c } from "../theme.js";
import { fieldBox, uiText } from "../styles.js";

// The fields of the square editor (SquareEditor.jsx and the choices it shows), so they look alike.

export const help = uiText(12, c.textFaint, { lineHeight: 1.5 });
export const box = () => ({ ...fieldBox(), padding: "5px 8px" });
export const label12 = uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 6 });
export const colourBox = { width: 30, height: 22, padding: 0, border: `1px solid ${c.border}`, background: "none", cursor: "pointer" };
