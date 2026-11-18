// What the Backups section's parts share: the trigger names, the "what changed" wording and the small buttons
import { fs } from "../../theme.js";
import { headerButton } from "../../styles.js";

export const TRIGGER = { manual: "by hand", automatic: "automatic", before_restore: "taken before a restore" };

// "2 changed, 1 added" since the backup before; the oldest kept has nothing to compare with
export const changesText = (ch) => {
  if (!ch) return "the oldest kept";
  const parts = [["changed", ch.changed], ["added", ch.added], ["removed", ch.removed]].filter(([, l]) => l.length).map(([w, l]) => `${l.length} ${w}`);
  return parts.length ? parts.join(", ") : "no changes";
};
export const changesHint = (ch) =>
  ch && [["Changed", ch.changed], ["Added", ch.added], ["Removed", ch.removed]].filter(([, l]) => l.length).map(([w, l]) => `${w}: ${l.join(", ")}`).join("\n");

export const smallButton = { ...headerButton(), padding: "3px 8px", fontSize: fs(11) };
export const iconButton = { ...headerButton(), padding: 0, width: 26, justifyContent: "center" };
