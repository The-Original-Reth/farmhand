import { useEffect, useRef, useState } from "react";

// What each camera tile says in its top right corner: what the camera runs on, and the picture size and frame rate it is
// actually sending, measured live. A value that can't be read (yet) is left out, never guessed from a setting.

// What the camera runs on. `crowsnest`: its ustreamer answered (below), so it's Crowsnest's MJPEG streamer.
export function cameraSource(cam, crowsnest) {
  if (cam.service === "farmhand-go2rtc") return "Buddy3D RTSP";
  if (cam.service === "webrtc-go2rtc") return "go2rtc";
  if (cam.service === "webrtc-camerastreamer") return "camera-streamer";
  if (cam.service === "iframe") return null;
  if (crowsnest) return "Crowsnest";
  return cam.mjpeg ? "MJPEG" : "Snapshots";
}

// The one line shown: "go2rtc · 1280×720 · 15 fps", or as much of it as is known
export function liveText(source, m) {
  return [source, m?.width && `${m.width}×${m.height}`, m?.fps != null && `${m.fps} fps`].filter(Boolean).join(" · ");
}

// Crowsnest's ustreamer reports what it is capturing at "state" beside its stream ("http://printer/webcam/?action=stream"
// -> "http://printer/webcam/state"), open to any page. Only for the MJPEG and snapshot cameras: a WebRTC one is measured
// from its own video.
const VIDEO_SERVICES = ["webrtc-go2rtc", "webrtc-camerastreamer", "farmhand-go2rtc", "iframe"];
export function ustreamerStateUrl(cam) {
  if (VIDEO_SERVICES.includes(cam.service)) return null;
  for (const u of [cam.stream_url, cam.snapshot_url]) {
    if (!u || !/[?&]action=(stream|snapshot)\b/.test(u)) continue;
    try {
      const x = new URL(u, window.location.href);
      x.search = "";
      x.hash = "";
      x.pathname = x.pathname.replace(/[^/]*$/, "") + "state";
      return x.href;
    } catch {
      // not an address: no state to ask
    }
  }
  return null;
}

const STATE_EVERY_MS = 3000;

// The camera's own numbers from its ustreamer, asked every few seconds while the page is in view: { width, height, fps }
// (fps: the frames it captured in the last second), or null while it hasn't answered or isn't ustreamer
export function useUstreamerState(url) {
  const [state, setState] = useState(null);
  useEffect(() => {
    setState(null);
    if (!url) return;
    let live = true;
    const ask = async () => {
      if (document.hidden) return;
      try {
        const r = await fetch(url, { cache: "no-store" });
        const src = (await r.json())?.result?.source;
        const size = src?.resolution;
        if (!live) return;
        if (!r.ok || !src?.online || !size?.width) return setState(null);
        const next = { width: size.width, height: size.height, fps: Number.isFinite(src.captured_fps) ? src.captured_fps : null };
        setState((now) => (same(now, next) ? now : next));
      } catch {
        if (live) setState(null);
      }
    };
    ask();
    const timer = setInterval(ask, STATE_EVERY_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [url]);
  return state;
}

export const same = (a, b) => a?.width === b?.width && a?.height === b?.height && a?.fps === b?.fps;

const MEASURE_EVERY_MS = 2000;

// Measures a playing <video>: its size as decoded, and the frames shown per second, counted with
// requestVideoFrameCallback (or the browser's own count of decoded frames where that's missing). A stretch when the
// page was out of view, or the stream restarted, isn't counted. Calls report({ width, height, fps }); returns a stop.
export function measureVideo(v, report) {
  let presented = null;
  let handle = null;
  const onFrame = (_, meta) => {
    presented = meta.presentedFrames;
    handle = v.requestVideoFrameCallback(onFrame);
  };
  if (v.requestVideoFrameCallback) handle = v.requestVideoFrameCallback(onFrame);
  const count = () => presented ?? v.getVideoPlaybackQuality?.().totalVideoFrames ?? null;
  let last = null;
  let fps = null;
  const tick = () => {
    const now = { t: performance.now(), n: count(), hidden: v.ownerDocument.hidden };
    if (last && !last.hidden && !now.hidden && now.n != null && last.n != null && now.n >= last.n) {
      fps = Math.round(((now.n - last.n) * 1000) / (now.t - last.t));
    }
    last = now;
    if (v.videoWidth) report({ width: v.videoWidth, height: v.videoHeight, fps });
  };
  const timer = setInterval(tick, MEASURE_EVERY_MS);
  return () => {
    clearInterval(timer);
    if (handle != null) v.cancelVideoFrameCallback?.(handle);
  };
}

// measureVideo on a <video> ref for as long as it is there, telling the newest onMeasure
export function useMeasuredVideo(video, onMeasure) {
  const tell = useRef(onMeasure);
  tell.current = onMeasure;
  useEffect(() => video.current && measureVideo(video.current, (m) => tell.current(m)), []);
}

// Counts pictures as they arrive (each snapshot loaded): call frame() for each, and rate() for the pictures per second
// over the last few seconds (null until it has been counting that long)
export function frameCounter(windowMs = 3000) {
  const began = performance.now();
  const times = [];
  const drop = (t) => {
    while (times.length && times[0] < t - windowMs) times.shift();
  };
  return {
    frame() {
      const t = performance.now();
      times.push(t);
      drop(t);
    },
    rate() {
      const t = performance.now();
      drop(t);
      return t - began < windowMs ? null : Math.round((times.length * 1000) / windowMs);
    },
  };
}
