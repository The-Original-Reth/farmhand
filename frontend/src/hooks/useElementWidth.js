import { useLayoutEffect, useRef, useState } from "react";

// How wide an element is, kept current as it changes (the window, the menu folding away): [ref for the element, its
// width in px, 0 until it's measured]. Measured before the first paint, so a layout chosen by it doesn't flash.
export function useElementWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => setWidth(Math.round(el.getBoundingClientRect().width));
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const seen = new ResizeObserver(measure);
    seen.observe(el);
    return () => seen.disconnect();
  }, []);
  return [ref, width];
}
