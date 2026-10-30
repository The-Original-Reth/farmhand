import { useState } from "react";
import { errorText } from "../api.js";

// Something sent from the page (a form's save, a button's change). `run(fn)` clears the last error, sets `busy` while
// `fn` is on its way, and keeps why it failed, as the page shows it, in `error`. It resolves to true when `fn` went
// through, false when it didn't. `setError` shows a reason found before sending anything ("Give it a name").
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, setError, run };
}
