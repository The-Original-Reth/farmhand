import { useEffect, useRef, useState } from "react";
import { c, fs, ui } from "../theme.js";
import { uiText } from "../styles.js";
import { errorText, getWebcams } from "../api.js";
import { useData } from "../data.jsx";

// Every printer's cameras, as set up in Mainsail and played the way Mainsail plays them, in one grid: the pictures
// only, each named in its corner. Click one to see it on its own, large; click again (or Esc) to go back to the grid.
export function MonitorSection() {
  const { printers } = useData();
  const [cams, setCams] = useState(null); // printer id -> { webcams, error }
  const [big, setBig] = useState(null); // the camera shown on its own: its key
  const active = printers.filter((p) => !p.decommissioned);
  const ids = active.map((p) => p.id).join(",");

  useEffect(() => {
    let live = true;
    Promise.all(active.map((p) => getWebcams(p.id).then((d) => [p.id, d], (e) => [p.id, { webcams: [], error: errorText(e) }])))
      .then((pairs) => live && setCams(Object.fromEntries(pairs)));
    return () => {
      live = false;
    };
  }, [ids]);

  useEffect(() => {
    if (!big) return;
    const close = (e) => e.key === "Escape" && setBig(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [big]);

  if (!cams) return <div style={uiText(13, c.textFaint)}>Finding the printers' cameras…</div>;

  // one tile per camera; a printer with two cameras gets two, named "VT 1190 · Nozzle"
  const tiles = active.flatMap((p) => {
    const list = cams[p.id]?.webcams || [];
    return list.map((cam, i) => ({ key: `${p.id}-${i}`, label: list.length > 1 ? `${p.name} · ${cam.name}` : p.name, cam }));
  });
  const without = active.filter((p) => !(cams[p.id]?.webcams || []).length);

  return (
    <div data-testid="monitor-section" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {tiles.length === 0 ? (
        <div style={uiText(13, c.textMuted, { lineHeight: 1.6 })}>
          No cameras yet. A printer's camera shows here once it's set up in Mainsail (Settings → Webcams).
        </div>
      ) : (
        <div
          data-testid="monitor-grid"
          style={{ display: "grid", gridTemplateColumns: big ? "1fr" : "repeat(auto-fill, minmax(min(340px, 100%), 1fr))", gap: 8 }}
        >
          {/* all stay mounted while one is enlarged, so no camera has to connect again on the way back */}
          {tiles.map((t) => (
            <CameraTile
              key={t.key} label={t.label} cam={t.cam} big={big === t.key} hidden={!!big && big !== t.key}
              onClick={() => setBig(big ? null : t.key)}
            />
          ))}
        </div>
      )}
      {without.length > 0 && !big && (
        <div data-testid="monitor-without" style={uiText(12, c.textFaint, { lineHeight: 1.7 })}>
          No camera:{" "}
          {without.map((p, i) => (
            <span key={p.id} title={cams[p.id]?.error || "No camera set up in Mainsail"}>
              {i > 0 && ", "}
              {p.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// A camera's own picture, turned and flipped as Mainsail is set to show it
function CameraTile({ label, cam, big, hidden, onClick }) {
  const [w, h] = String(cam.aspect_ratio || "16:9").split(":").map(Number);
  const [state, setState] = useState("waiting"); // waiting | showing | failed
  const turn = [
    cam.rotation ? `rotate(${cam.rotation}deg)` : "",
    cam.flip_horizontal ? "scaleX(-1)" : "",
    cam.flip_vertical ? "scaleY(-1)" : "",
  ].join(" ").trim();
  const fill = { width: "100%", height: "100%", objectFit: "contain", display: "block", border: 0, transform: turn || undefined };

  return (
    <div
      data-testid="monitor-camera"
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onClick())}
      title={big ? "Back to all cameras" : `See ${label} on its own`}
      style={{
        position: "relative", aspectRatio: w && h ? `${w} / ${h}` : "16 / 9", maxHeight: big ? "calc(100vh - 170px)" : undefined,
        display: hidden ? "none" : undefined,
        background: "#000", border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden", cursor: big ? "zoom-out" : "zoom-in",
      }}
    >
      <CameraPicture cam={cam} label={label} style={fill} onState={setState} />
      {state !== "showing" && (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", ...ui, fontSize: fs(12), color: "#8a9198" }}>
          {state === "failed" ? "The camera isn't answering" : "Waiting for the camera…"}
        </div>
      )}
      <div
        style={{
          position: "absolute", left: 6, bottom: 6, padding: "2px 7px", borderRadius: 3, background: "rgba(0,0,0,0.55)",
          color: "#e6e8ea", ...ui, fontSize: fs(11), pointerEvents: "none",
        }}
      >
        {label}
      </div>
    </div>
  );
}

// The camera played by the service Mainsail has it set to:
//   mjpegstreamer, uv4l-mjpeg, ipstream   the MJPEG stream itself, in an <img>
//   webrtc-go2rtc                         WebRTC, set up over go2rtc's websocket
//   webrtc-camerastreamer                 WebRTC, set up with camera-streamer's POSTs
//   iframe                                the stream address in a frame
//   anything else (the adaptive MJPEG one, HLS, ...)  its snapshots, at the frame rate set in Mainsail
function CameraPicture({ cam, label, style, onState }) {
  const s = cam.service;
  if (s === "webrtc-go2rtc" && cam.stream_url) return <WebrtcVideo cam={cam} connect={go2rtc} style={style} onState={onState} />;
  if (s === "webrtc-camerastreamer" && cam.stream_url) return <WebrtcVideo cam={cam} connect={cameraStreamer} style={style} onState={onState} />;
  if (s === "iframe" && cam.stream_url) return <iframe src={cam.stream_url} title={label} style={{ ...style, pointerEvents: "none" }} onLoad={() => onState("showing")} />;
  if (cam.mjpeg) return <img src={cam.stream_url} alt={label} style={style} onLoad={() => onState("showing")} onError={() => onState("failed")} />;
  return <Snapshots cam={cam} label={label} style={style} onState={onState} />;
}

// The next snapshot is fetched once the last one has loaded, no faster than the camera's frame rate, and only while the
// page is in view. It replaces the last picture only once loaded, so the picture never blanks in between.
function Snapshots({ cam, label, style, onState }) {
  const [src, setSrc] = useState(null);
  const url = cam.snapshot_url;

  useEffect(() => {
    if (!url) return onState("failed");
    let live = true;
    let timer;
    const gap = 1000 / Math.max(1, cam.target_fps || 15);
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
    };
  }, [url, cam.target_fps]);

  return src ? <img src={src} alt={label} style={style} /> : null;
}

// A WebRTC camera: `connect` sets up the peer connection its own way; the picture plays muted, as a camera has no sound
// worth hearing. A dropped connection is tried again after a few seconds.
function WebrtcVideo({ cam, connect, style, onState }) {
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
