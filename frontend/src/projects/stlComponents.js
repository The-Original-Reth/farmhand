// The sub-components a project's STLs are in: how one is shown, and the STLs grouped by them
import { nameCollator } from "../lib/order.js";

// A sub-component as it's shown: "Body/Fins" is "Body / Fins"
export const shown = (component) => component.split("/").join(" / ");

// The STLs in the project's sub-components: those in none first, then each sub-component, by name ("Body" just before
// "Body/Fins"). [{ component (null: none), items }]
export function inComponents(items) {
  const named = new Map();
  for (const item of items.filter((i) => i.component)) {
    if (!named.has(item.component)) named.set(item.component, []);
    named.get(item.component).push(item);
  }
  return [
    { component: null, items: items.filter((i) => !i.component) },
    ...[...named.keys()].sort(nameCollator.compare).map((component) => ({ component, items: named.get(component) })),
  ];
}
