// Putting things in order: names as a person reads them, and things put in order by dragging one onto another
// (Monitor's cameras, Farm cost's printers), the order kept on the server as a list of keys.

export const nameCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" }); // "Part 2" before "Part 10"

// The keys in the order kept, then any not in it yet in the order they come (a new camera, a new printer)
export function arranged(keys, order) {
  const here = new Set(keys);
  const kept = order.filter((k) => here.has(k));
  return [...kept, ...keys.filter((k) => !kept.includes(k))];
}

// The order after `dragged` is dropped on `target`: it takes the target's place, and the ones between move along one
// to make room.
export function moved(keys, dragged, target) {
  const next = keys.filter((k) => k !== dragged);
  next.splice(keys.indexOf(target), 0, dragged);
  return next;
}
