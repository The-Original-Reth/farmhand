import { useState } from "react";
import { ChevronRight, Download, FileBox, Trash2 } from "lucide-react";
import { c, fs, ui } from "../../theme.js";
import { monoText, uiText } from "../../styles.js";

export function Badge({ children, tone = "muted" }) {
  const tones = {
    muted: { bg: c.panelAlt, fg: c.textMuted, border: c.border },
    amber: { bg: c.amberDim, fg: c.amber, border: c.amberBorder },
    teal: { bg: c.tealDim, fg: c.teal, border: c.tealBorder },
    green: { bg: c.greenDim, fg: c.green, border: c.greenBorder },
    danger: { bg: c.dangerDim, fg: c.danger, border: c.danger },
  };
  const t = tones[tone];
  return (
    <span
      style={{
        ...ui,
        fontSize: fs(12),
        padding: "2px 8px",
        borderRadius: 3,
        background: t.bg,
        color: t.fg,
        border: `1px solid ${t.border}`,
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

export function Row({ children, onClick, hoverable = true }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        alignItems: "center",
        padding: "12px 16px",
        borderBottom: `1px solid ${c.border}`,
        background: hoverable && hover ? c.panelHover : "transparent",
        cursor: onClick ? "pointer" : "default",
        transition: "background 0.1s ease",
      }}
    >
      {children}
    </div>
  );
}

export function SectionLabel({ children }) {
  return (
    <div style={uiText(13, c.textFaint, { marginBottom: 10 })}>
      {children}
    </div>
  );
}

export function DownloadButton({ disabled, href }) {
  const style = {
    display: "flex",
    alignItems: "center",
    gap: 5,
    border: `1px solid ${disabled ? c.border : c.borderStrong}`,
    background: disabled ? "transparent" : c.panelAlt,
    color: disabled ? c.textFaint : c.textMuted,
    borderRadius: 3,
    padding: "4px 9px",
    fontSize: fs(12),
    cursor: disabled ? "not-allowed" : "pointer",
    textDecoration: "none",
    ...ui,
  };
  const title = disabled ? "Original file pruned — parameters only" : "Download";
  if (disabled || !href) {
    return (
      <button onClick={(e) => e.stopPropagation()} disabled={disabled} title={title} style={style}>
        <Download size={12} />
        Download
      </button>
    );
  }
  return (
    <a href={href} onClick={(e) => e.stopPropagation()} title={title} style={style} download>
      <Download size={12} />
      Download
    </a>
  );
}

// Square preview tile. Renders a real embedded/rendered image when given one;
// falls back to a quiet placeholder otherwise.
export function Thumb({ src, size = 36, plateGrid = false, background, placeholderIcon = false }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: 3,
        border: `1px solid ${c.border}`,
        background: background || c.panelAlt,
        overflow: "hidden",
        flexShrink: 0,
        position: "relative",
      }}
    >
      {src ? (
        <img src={src} alt="" loading="lazy" decoding="async" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
      ) : placeholderIcon ? (
        <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <FileBox size={Math.round(size * 0.4)} color="#C7CACC" />
        </div>
      ) : (
        <div style={{ width: "100%", height: "100%" }} />
      )}
      {plateGrid && (
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 3,
            background: c.borderStrong,
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Deleting
// ---------------------------------------------------------------------------
export function TrashButton({ onClick, title }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title={title}
      aria-label={title}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: 26,
        height: 26,
        flexShrink: 0,
        borderRadius: 3,
        border: `1px solid ${hover ? c.danger : c.border}`,
        background: hover ? c.dangerDim : "transparent",
        color: hover ? c.danger : c.textFaint,
        cursor: "pointer",
      }}
    >
      <Trash2 size={13} />
    </button>
  );
}


// A bar filled `pct` (0-100) of the way, in `color`. `smooth`: the fill slides to each new value (for progress that
// moves while you watch); `style` adds to the track (its margin, a narrower one).
export function ProgressBar({ pct, color = c.amber, height = 6, smooth = false, style }) {
  return (
    <div style={{ height, borderRadius: height / 2, background: c.panelAlt, overflow: "hidden", ...style }}>
      <div style={{ width: `${Math.min(100, pct || 0)}%`, height: "100%", background: color, ...(smooth && { transition: "width 0.2s ease" }) }} />
    </div>
  );
}

export function StatTile({ label, value, hint }) {
  return (
    <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: "10px 12px", background: c.panelAlt, minWidth: 0 }} title={hint}>
      <div style={uiText(11, c.textFaint, { marginBottom: 4 })}>{label}</div>
      <div style={monoText(16, c.heading, { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" })}>{value}</div>
    </div>
  );
}

// A section heading that folds the section away or opens it again
// indent: moves it right (px), for a section inside another
export function SectionToggle({ open, onToggle, controlsId, testId, indent = 0, children }) {
  return (
    <button
      data-testid={testId}
      aria-expanded={open}
      aria-controls={controlsId}
      onClick={onToggle}
      title={open ? "Fold away" : "Show"}
      style={{ display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", padding: 0, marginLeft: indent, cursor: "pointer", ...ui, fontSize: fs(13), color: open ? c.textFaint : c.textMuted, textAlign: "left" }}
    >
      <ChevronRight size={14} style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform 0.12s ease", flexShrink: 0 }} />
      {children}
    </button>
  );
}
