import { useEffect, useState } from "react";

// The 3MF versions picked to compare (the tray at the bottom of the page) and whether the compare is open.
// `versionIndex`: every version by id, so the pair can be drawn and deleted versions dropped from the picks.
export function useCompare(versionIndex) {
  const [selection, setSelection] = useState([]); // VERSION ids, in selection order
  const [open, setOpen] = useState(false);

  // Drop deleted versions from the compare selection
  useEffect(() => {
    setSelection((prev) => {
      const next = prev.filter((id) => versionIndex[id]);
      if (next.length === prev.length) return prev;
      setOpen(false);
      return next;
    });
  }, [versionIndex]);

  // every change to the picks closes the compare, so it never shows a pair that's no longer picked
  const pick = (change) => {
    setSelection(change);
    setOpen(false);
  };
  return {
    selection,
    // A compare is between two versions: picking a third replaces the oldest pick instead of being ignored
    toggle: (versionId) =>
      pick((prev) =>
        prev.includes(versionId) ? prev.filter((id) => id !== versionId) : prev.length >= 2 ? [prev[1], versionId] : [...prev, versionId]
      ),
    remove: (versionId) => pick((prev) => prev.filter((id) => id !== versionId)),
    clear: () => pick([]),
    open: open && versionIndex[selection[0]] && versionIndex[selection[1]] ? [versionIndex[selection[0]], versionIndex[selection[1]]] : null,
    show: () => setOpen(true),
    close: () => setOpen(false),
  };
}
