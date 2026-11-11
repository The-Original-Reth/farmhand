// What this browser remembers (localStorage), as JSON. Storage can be unavailable (a private window, blocked site
// data) or hold something unreadable: then a read finds nothing and a write is simply not remembered.

// The value kept under `key`, or null when there's none (or it can't be read)
export function readStored(key) {
  try {
    return JSON.parse(localStorage.getItem(key));
  } catch {
    return null;
  }
}

// The same, for a value that has to be an object ({ id: choice }): anything else reads as {}
export function readStoredObject(key) {
  const v = readStored(key);
  return v && typeof v === "object" && !Array.isArray(v) ? v : {};
}

// Keep `value` under `key`; null (or undefined) forgets it
export function writeStored(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: it just isn't remembered */
  }
}
