import { useEffect, useRef, useState } from "react";

// The camera played by the service Mainsail has it set to:
//   mjpegstreamer, uv4l-mjpeg, ipstream   the MJPEG stream itself, in an <img>
//   webrtc-go2rtc                         WebRTC, set up over go2rtc's websocket
//   webrtc-camerastreamer                 WebRTC, set up with camera-streamer's POSTs
//   iframe                                the stream address in a frame
//   anything else (the adaptive MJPEG one, HLS, ...)  its snapshots, at the frame rate set in Mainsail
export function CameraPicture({ cam, label, style, onState }) {
  const s = cam.service;
  if (s === "webrtc-go2rtc" && cam.stream_url) return <WebrtcVideo cam={cam} connect={go2rtc} style={style} onState={onState} />;
  if (s === "webrtc-camerastreamer" && cam.stream_url) return <WebrtcVideo cam={cam} connect={cameraStreamer} style={style} onState={onState} />;
  if (s === "iframe" && cam.stream_url) return <iframe src={cam.stream_url} title={label} style={{ ...style, pointerEvents: "none" }} onLoad={() => onState("showing")} />;
  if (cam.mjpeg) return <img src={cam.stream_url} alt={label} draggable={false} style={style} onLoad={() => onState("showing")} onError={() => onState("failed")} />;
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

  return src ? <img src={src} alt={label} draggable={false} style={style} /> : null;
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
