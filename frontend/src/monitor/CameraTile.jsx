import { useState } from "react";
import { c, fs, ui } from "../theme.js";
import { CameraPicture } from "./players.jsx";
import { TILE } from "./wall.js";

// A camera's own picture, turned and flipped as Mainsail is set to show it
export function CameraTile({ label, cam, big, hidden, place, moving, target, drag, onClick }) {
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
      title={big ? "Back to all cameras" : `See ${label} on its own, or drag it to move it`}
      draggable={!!drag}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", label);
        drag?.start();
      }}
      onDragEnter={() => drag?.enter()}
      onDragOver={(e) => drag && e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        drag?.drop();
      }}
      onDragEnd={() => drag?.end()}
      style={{
        position: "relative", aspectRatio: `${TILE}`,
        display: hidden ? "none" : undefined, order: place, opacity: moving ? 0.4 : 1,
        outline: target ? `2px solid ${c.amber}` : "none", outlineOffset: 2,
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
