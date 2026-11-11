import { useEffect, useState } from "react";

// The preview's clocks: its own count of seconds, for taking turns while it isn't in step with the server; the
// server's time of day, while it is; and a slideshow played (or gone through by hand) in the square being edited.

// Seconds counted from 0 while `on`, starting again whenever one of `deps` changes
export function useSecondsSince(on, deps) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!on) return;
    setSeconds(0);
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [on, ...deps]);
  return seconds;
}

// The server's time of day now, in seconds (its own, not this computer's: a clock that's a little out doesn't
// matter), from `serverClock` { serverTime, heardAt } (the last status, and when it came); null without one. Slideshows
// and taking turns count from it, as the stream does, so the preview shows what the stream shows (or will start on).
export function useServerClock(serverClock) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!serverClock) return;
    const timer = setInterval(() => setTick((t) => t + 1), 250);
    return () => clearInterval(timer);
  }, [!!serverClock]);
  return serverClock ? serverClock.serverTime + (Date.now() - serverClock.heardAt) / 1000 : null;
}

// A slideshow of `slides` pictures, `seconds` each, in the square being edited (`square`: starts again on another):
// which picture is on show, and whether it goes round on its own. null when `on` is false (no slideshow there).
// { at, playing, go(at), step(by), play(), stop() }
export function useSlidePlayer(slides, seconds, square, on) {
  const [slide, setSlide] = useState({ at: 0, playing: true });
  useEffect(() => setSlide({ at: 0, playing: true }), [square]);
  useEffect(() => {
    if (!slide.playing || slides < 2) return;
    const timer = setInterval(() => setSlide((s) => ({ ...s, at: (s.at + 1) % slides })), Math.max(1, Number(seconds) || 10) * 1000);
    return () => clearInterval(timer);
  }, [slide.playing, slides, seconds, square]);
  if (!on) return null;
  return {
    at: slides ? slide.at % slides : 0, playing: slide.playing,
    go: (at) => setSlide((s) => ({ ...s, at })),
    // one picture on or back, from where it is now (so quick clicks each count), and held there
    step: (by) => setSlide((s) => ({ playing: false, at: (((s.at % slides) + by) % slides + slides) % slides })),
    play: () => setSlide((s) => ({ ...s, playing: true })),
    stop: () => setSlide((s) => ({ ...s, playing: false })),
  };
}
