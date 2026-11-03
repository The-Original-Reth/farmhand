// A printer's own web page: PrusaLink for a Prusa reached that way, Mainsail for a Klipper one. { url, name }, or null
// when Farmhand has no address for it. Used by the Mainsail / PrusaLink buttons and the links on Monitor's cameras.
export function webUiOf(printer) {
  const prusa = printer.connectionType === "prusalink";
  const url = prusa ? printer.prusalinkUrl : printer.mainsailUrl;
  return url ? { url, name: prusa ? "PrusaLink" : "Mainsail" } : null;
}
