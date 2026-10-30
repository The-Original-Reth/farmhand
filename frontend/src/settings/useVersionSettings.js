import { useEffect, useState } from "react";
import { errorText, fetchVersionSettings } from "../api.js";

// A 3MF version's settings, loaded when `versionId` changes: { settings, error }. Both are null while it loads,
// and stay null with no version. An answer for a version that's no longer asked for is dropped.
export function useVersionSettings(versionId) {
  const [state, setState] = useState({ settings: null, error: null });
  useEffect(() => {
    let cancelled = false;
    setState({ settings: null, error: null });
    if (versionId == null) return undefined;
    fetchVersionSettings(versionId)
      .then((settings) => !cancelled && setState({ settings, error: null }))
      .catch((e) => !cancelled && setState({ settings: null, error: errorText(e) }));
    return () => {
      cancelled = true;
    };
  }, [versionId]);
  return state;
}
