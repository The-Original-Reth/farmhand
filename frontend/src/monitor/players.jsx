import { useEffect, useRef, useState } from "react";
import { frameCounter, useMeasuredVideo } from "./liveInfo.js";

// The camera played by the service Mainsail has it set to:
//   mjpegstreamer, uv4l-mjpeg, ipstream   the MJPEG stream itself, in an <img>
//   webrtc-go2rtc                         WebRTC, set up over go2rtc's websocket
//   webrtc-camerastreamer                 WebRTC, set up with camera-streamer's POSTs
//   iframe                                the stream address in a frame
//   anything else (the adaptive MJPEG one, HLS, ...)  its snapshots, at the frame rate set in Mainsail
// and a camera Farmhand plays itself (a Buddy3D's, "farmhand-go2rtc"): video sent over go2rtc's websocket.
// onMeasure({ width, height, fps }) is told what the picture really is, as far as this browser can see it: a video's
// decoded size and frames shown per second, snapshots' size and how many arrive per second, an MJPEG stream's size
// (its frames can't be counted from an <img>).
export function CameraPicture({ cam, label, style, onState, onMeasure = () => {} }) {
  const s = cam.service;
  if (s === "farmhand-go2rtc" && cam.stream_url) return <StreamedVideo cam={cam} style={style} onState={onState} onMeasure={onMeasure} />;
  if (s === "webrtc-go2rtc" && cam.stream_url) return <WebrtcVideo cam={cam} connect={go2rtc} style={style} onState={onState} onMeasure={onMeasure} />;
  if (s === "webrtc-camerastreamer" && cam.stream_url) return <WebrtcVideo cam={cam} connect={cameraStreamer} style={style} onState={onState} onMeasure={onMeasure} />;
  if (s === "iframe" && cam.stream_url) return <iframe src={cam.stream_url} title={label} style={{ ...style, pointerEvents: "none" }} onLoad={() => onState("showing")} />;
  if (cam.mjpeg) return <img src={cam.stream_url} alt={label} draggable={false} style={style} onLoad={(e) => (onState("showing"), onMeasure({ width: e.currentTarget.naturalWidth || null, height: e.currentTarget.naturalHeight, fps: null }))} onError={() => onState("failed")} />;
  return <Snapshots cam={cam} label={label} style={style} onState={onState} onMeasure={onMeasure} />;
}

// The next snapshot is fetched once the last one has loaded, no faster than the camera's frame rate, and only while the
// page is in view. It replaces the last picture only once loaded, so the picture never blanks in between.
function Snapshots({ cam, label, style, onState, onMeasure }) {
  const [src, setSrc] = useState(null);
  const url = cam.snapshot_url;

  useEffect(() => {
    if (!url) return onState("failed");
    let live = true;
    let timer;
    const gap = 1000 / Math.max(1, cam.target_fps || 15);
    const counted = frameCounter();
    let size = null;
    const measure = setInterval(() => !document.hidden && size && onMeasure({ ...size, fps: counted.rate() }), 2000);
    const fresh = () => (/^https?:/i.test(url) ? `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}` : url);
    const next = () => {
      if (!live) return;
      if (document.hidden) return (timer = setTimeout(next, 1000));
      const began = Date.now();
      const img = new Image();
      const again = (wait) => live && (timer = setTimeout(next, wait));
      img.onload = () => {
        if (!live) return;
        setSrc(img.src);
        onState("showing");
        counted.frame();
        size = img.naturalWidth ? { width: img.naturalWidth, height: img.naturalHeight } : null;
        again(Math.max(0, gap - (Date.now() - began)));
      };
      img.onerror = () => {
        if (!live) return;
        onState("failed");
        again(3000);
      };
      img.src = fresh();
    };
    next();
    return () => {
      live = false;
      clearTimeout(timer);
      clearInterval(measure);
    };
  }, [url, cam.target_fps]);

  return src ? <img src={src} alt={label} draggable={false} style={style} /> : null;
}

// A WebRTC camera: `connect` sets up the peer connection its own way; the picture plays muted, as a camera has no sound
// worth hearing. A dropped connection is tried again after a few seconds.
function WebrtcVideo({ cam, connect, style, onState, onMeasure }) {
  const video = useRef(null);

  useEffect(() => {
    let live = true;
    let stop = () => {};
    let retry;
    const start = () => {
      const pc = new RTCPeerConnection();
      let over = false; // this try is over: fail only once for it
      const fail = () => {
        if (!live || over) return;
        over = true;
        onState("failed");
        stop();
        retry = setTimeout(start, 5000);
      };
      pc.ontrack = (e) => {
        if (video.current) video.current.srcObject = e.streams[0] || new MediaStream([e.track]);
      };
      pc.onconnectionstatechange = () => ["failed", "disconnected"].includes(pc.connectionState) && fail();
      const hangUp = connect(pc, cam.stream_url, fail);
      stop = () => {
        hangUp?.();
        pc.close();
      };
    };
    start();
    return () => {
      live = false;
      clearTimeout(retry);
      stop();
    };
  }, [cam.stream_url]);

  useMeasuredVideo(video, onMeasure);

  return (
    <video
      ref={video} autoPlay muted playsInline style={style}
      onPlaying={() => onState("showing")}
    />
  );
}

// go2rtc, as Mainsail talks to it: its stream page ("http://host:1984/stream.html?src=chamber") becomes the websocket
// beside it ("ws://host:1984/api/ws?src=chamber"); the offer, answer and candidates go back and forth over it.
function go2rtc(pc, streamUrl, fail) {
  const u = new URL(streamUrl);
  const src = u.searchParams.get("src");
  u.pathname = u.pathname.replace(/[^/]*$/, "") + "api/ws";
  u.search = src ? `?src=${encodeURIComponent(src)}` : "";
  u.hash = "";
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  pc.addTransceiver("video", { direction: "recvonly" });
  const ws = new WebSocket(u);
  const send = (type, value) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type, value }));
  pc.onicecandidate = (e) => e.candidate && send("webrtc/candidate", e.candidate.candidate);
  ws.onopen = async () => {
    try {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      send("webrtc/offer", offer.sdp);
    } catch {
      fail();
    }
  };
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === "webrtc/answer") pc.setRemoteDescription({ type: "answer", sdp: msg.value }).catch(fail);
    else if (msg.type === "webrtc/candidate") pc.addIceCandidate({ candidate: msg.value, sdpMid: "0" }).catch(() => {});
    else if (msg.type === "error") fail();
  };
  ws.onerror = fail;
  return () => ws.close();
}

// camera-streamer: the stream address answers a POSTed request with its offer; the answer and this side's candidates
// are POSTed back to it.
function cameraStreamer(pc, streamUrl, fail) {
  const post = (body) =>
    fetch(streamUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  (async () => {
    const offer = await (await post({ type: "request", res: null })).json();
    pc.onicecandidate = (e) => e.candidate && post({ type: "remote_candidate", id: offer.id, candidates: [e.candidate] });
    await pc.setRemoteDescription(offer);
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    await post({ type: "answer", id: offer.id, sdp: answer.sdp });
  })().catch(fail);
}

// The video go2rtc can send over the websocket itself (MSE): fragments of MP4 the browser adds to a <video> as they come.
// Unlike WebRTC it needs no ports beyond the web page's own, so it passes through Farmhand's web server
// ("/go2rtc/api/ws?src=farmhand_5" on the address the page came from). It stays near the newest picture, keeps only
// the last few seconds, and connects again a few seconds after a drop.
const CODECS = ["avc1.640029", "avc1.64002A", "avc1.640033", "hvc1.1.6.L153.B0", "mp4a.40.2", "mp4a.40.5", "opus"];
const KEEP = 10; // seconds of video kept behind the newest

function StreamedVideo({ cam, style, onState, onMeasure }) {
  const video = useRef(null);

  useEffect(() => {
    let live = true;
    let retry;
    let stop = () => {};
    const start = () => {
      const page = new URL(cam.stream_url, window.location.href);
      page.protocol = page.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(page);
      ws.binaryType = "arraybuffer";
      const ms = new MediaSource();
      let buffer = null;
      const waiting = []; // pieces that came while the buffer was busy (or not made yet)
      let over = false;
      const fail = () => {
        if (!live || over) return;
        over = true;
        onState("failed");
        stop();
        retry = setTimeout(start, 5000);
      };
      const feed = () => {
        if (!buffer || buffer.updating || !waiting.length) return;
        const r = buffer.buffered;
        if (r.length && r.end(r.length - 1) - r.start(0) > KEEP * 2) return buffer.remove(0, r.end(r.length - 1) - KEEP);
        const piece = waiting.length === 1 ? waiting.shift() : join(waiting.splice(0));
        try {
          buffer.appendBuffer(piece);
        } catch {
          fail();
        }
      };
      ws.onopen = () => {
        const ok = CODECS.filter((c) => MediaSource.isTypeSupported(`video/mp4; codecs="${c}"`));
        ws.send(JSON.stringify({ type: "mse", value: ok.join(",") }));
      };
      ws.onmessage = (e) => {
        if (typeof e.data !== "string") {
          waiting.push(e.data);
          return feed();
        }
        const msg = JSON.parse(e.data);
        if (msg.type === "error") return fail();
        if (msg.type !== "mse") return;
        const v = video.current;
        if (!v) return;
        ms.addEventListener("sourceopen", () => {
          try {
            buffer = ms.addSourceBuffer(msg.value);
          } catch {
            return fail();
          }
          buffer.mode = "segments";
          buffer.addEventListener("updateend", () => {
            // fallen behind (a tab in the background, a slow moment): jump to the newest picture
            const r = buffer.buffered;
            if (r.length && v.currentTime < r.end(r.length - 1) - 3) v.currentTime = r.end(r.length - 1) - 0.5;
            feed();
          });
          feed();
        }, { once: true });
        v.src = URL.createObjectURL(ms);
        v.play().catch(() => {});
      };
      ws.onerror = fail;
      ws.onclose = fail;
      stop = () => {
        ws.onclose = null;
        ws.close();
        if (video.current) video.current.removeAttribute("src");
      };
    };
    start();
    return () => {
      live = false;
      clearTimeout(retry);
      stop();
    };
  }, [cam.stream_url]);

  useMeasuredVideo(video, onMeasure);

  return <video ref={video} autoPlay muted playsInline style={style} onPlaying={() => onState("showing")} />;
}

function join(pieces) {
  const out = new Uint8Array(pieces.reduce((n, p) => n + p.byteLength, 0));
  let at = 0;
  for (const p of pieces) {
    out.set(new Uint8Array(p), at);
    at += p.byteLength;
  }
  return out;
}
