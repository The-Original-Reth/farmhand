import { useEffect, useState } from "react";

// Whether a CSS media query matches (useMediaQuery("(max-width: 900px)")), kept current as the window changes
export function useMediaQuery(query) {
  const read = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false);
  const [matches, setMatches] = useState(read);
  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

// A phone, or any window this narrow: the menu folds away behind a button and pages lay out in one column
export const PHONE = "(max-width: 760px)";
export const usePhone = () => useMediaQuery(PHONE);
