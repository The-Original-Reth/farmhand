import { useEffect, useState } from "react";
import { cameraPictureUrl } from "../api.js";

// A camera in the Stream page's preview. Farmhand's Monitor plays each camera from the camera itself; the plugin's page
// only talks to its plugin, so it shows the camera's latest picture as the plugin gives it (its feeder's while live, its
// snapshot otherwise), a few times a second while the page is in view. A picture replaces the last only once loaded.
const EVERY_MS = 500;

export function CameraPicture({ cam, label, style, onState }) {
  const [src, setSrc] = useState(null);
  const url = cameraPictureUrl(cam.printer_id, cam.name);

  useEffect(() => {
    let live = true;
    let timer;
    const next = () => {
      if (!live) return;
      if (document.hidden) return (timer = setTimeout(next, 1000));
      const img = new Image();
      img.onload = () => {
        if (!live) return;
        setSrc(img.src);
        onState("showing");
        timer = setTimeout(next, EVERY_MS);
      };
      img.onerror = () => {
        if (!live) return;
        onState("failed");
        timer = setTimeout(next, 3000);
      };
      img.src = `${url}?t=${Date.now()}`;
    };
    next();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [url]);

  return src ? <img src={src} alt={label} draggable={false} style={style} /> : null;
}
