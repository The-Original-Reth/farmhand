import { useEffect, useState } from "react";
import { errorText } from "../api.js";

// Something the page reads when it opens, and again when one of `deps` changes: `load()` is asked, and its answer is
// `data` (null until the first one), or why it failed, as the page shows it, `error` (cleared by the next answer).
// What was read stays shown while it's read again, and an answer that comes after `deps` changed, or after the page
// closed, is dropped.
export function useLoad(load, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    load().then(
      (d) => live && (setData(d), setError(null)),
      (e) => live && setError(errorText(e)),
    );
    return () => {
      live = false;
    };
  }, deps);
  return { data, error };
}
