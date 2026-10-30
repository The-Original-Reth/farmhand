import { useState } from "react";
import { StickyNote } from "lucide-react";
import { c } from "../theme.js";
import { uiText } from "../styles.js";

import { Badge, Thumb } from "../components/common/ui.jsx";
import { Highlighted } from "../lib/search.jsx";
import { notesHint } from "../lib/format.js";

export function ModelListRow({ model, bundleCount, printerCount, borderBottom, borderRight, onOpen, words = [], reasons = [] }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      data-testid="model-row"
      onClick={onOpen}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        minWidth: 0,
        padding: "10px 14px",
        cursor: "pointer",
        background: hover ? c.panelAlt : "transparent",
        borderBottom: borderBottom ? `1px solid ${c.border}` : "none",
        borderRight: borderRight ? `1px solid ${c.border}` : "none",
      }}
    >
      <Thumb src={model.thumb} size={56} background="#FFFFFF" placeholderIcon />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          data-testid="model-name"
          title={model.name}
          style={uiText(14, c.heading, { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}
        >
          <Highlighted text={model.name} words={words} />
        </div>
        <div style={uiText(11, c.textFaint, { marginTop: 3 })}>Added {model.added}</div>
        {reasons.length > 0 && (
          <div
            data-testid="search-reason"
            title={reasons.join("\n")}
            style={uiText(11, c.teal, { marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}
          >
            Matched: {reasons.slice(0, 2).join(", ")}
            {reasons.length > 2 ? "…" : ""}
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 6, flexShrink: 0, alignItems: "center" }}>
        {model.notes && (
          <span data-testid="has-notes" title={notesHint(model.notes)} style={{ display: "flex" }}>
            <StickyNote size={14} color={c.textFaint} />
          </span>
        )}
        <Badge>{model.type}</Badge>
        <Badge tone="teal">{bundleCount} 3MF</Badge>
        <Badge tone="teal">{printerCount} {printerCount === 1 ? "Printer" : "Printers"}</Badge>
      </div>
    </div>
  );
}
