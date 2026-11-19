// A printer's own web page: PrusaLink for a Prusa reached that way, Mainsail for a Klipper one. { url, name }, or null
// when Farmhand has no address for it. Used by the Mainsail / PrusaLink buttons and the links on Monitor's cameras.
// What a Prusa printer is reached through, by name: "PrusaLink", or the plugin it's connected through ("Prusa Connect")
export const prusaVia = (printer) => (printer.statusFrom ? printer.statusFromName || "Prusa Connect" : "PrusaLink");

export function webUiOf(printer) {
  // connected through a plugin (Prusa Connect): its page there, never its PrusaLink
  if (printer.statusFrom) return printer.statusLink ? { url: printer.statusLink, name: printer.statusFromName || "Prusa Connect" } : null;
  const prusa = printer.connectionType === "prusalink";
  const url = prusa ? printer.prusalinkUrl : printer.mainsailUrl;
  return url ? { url, name: prusa ? "PrusaLink" : "Mainsail" } : null;
}
