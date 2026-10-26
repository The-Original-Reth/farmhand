import { CheckSquare, GitCompare, Square, X } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { monoText, uiText } from "../styles.js";
import { useData } from "../data.jsx";

export function CompareSelectButton({ selected, onClick }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      title={selected ? "Remove from compare" : "Select for compare"}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 5,
        ...ui,
        fontSize: fs(12),
        border: `1px solid ${selected ? c.amber : c.border}`,
        background: selected ? c.amberDim : "transparent",
        color: selected ? c.amber : c.textMuted,
        borderRadius: 3,
        padding: "4px 9px",
        cursor: "pointer",
      }}
    >
      {selected ? <CheckSquare size={13} /> : <Square size={13} />}
      {selected ? "Selected" : "Compare"}
    </button>
  );
}

export function CompareTray({ selection, onRemove, onCompare, onClear }) {
  const { versionIndex, versionLabel } = useData();
  if (selection.length === 0) return null;
  return (
    <div
      data-testid="compare-tray"
      style={{
        position: "fixed",
        left: 220,
        right: 0,
        bottom: 0,
        background: c.panel,
        borderTop: `1px solid ${c.borderStrong}`,
        padding: "12px 24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        zIndex: 40,
        boxShadow: "0 -4px 16px rgba(0,0,0,0.3)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", flex: 1, minWidth: 0 }}>
        <span style={uiText(12, c.textFaint, { flexShrink: 0 })}>
          Selected for compare ({selection.length}):
        </span>
        {selection.map((id, i) => {
          const entry = versionIndex[id];
          if (!entry) return null;
          return (
            <div
              key={id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                border: `1px solid ${i === 0 ? c.amber : i === 1 ? c.teal : c.border}`,
                background: i === 0 ? c.amberDim : i === 1 ? c.tealDim : c.panelAlt,
                borderRadius: 3,
                padding: "4px 8px",
              }}
            >
              <span data-testid="compare-chip" style={monoText(11, c.textPrimary)}>{versionLabel(entry)}</span>
              <button
                onClick={() => onRemove(id)}
                title="Unselect"
                style={{ background: "none", border: "none", color: c.textFaint, cursor: "pointer", padding: 0, display: "flex" }}
              >
                <X size={12} />
              </button>
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <button
          onClick={onClear}
          style={{
            ...ui,
            fontSize: fs(12),
            background: "none",
            color: c.textFaint,
            border: "none",
            cursor: "pointer",
            padding: "6px 4px",
          }}
        >
          Clear
        </button>
        {selection.length >= 2 && (
          <button
            data-testid="compare-go"
            onClick={onCompare}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              ...ui,
              fontSize: fs(13),
              background: c.amber,
              color: c.onAccent,
              border: "none",
              borderRadius: 4,
              padding: "8px 14px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            <GitCompare size={13} />
            Compare
          </button>
        )}
      </div>
    </div>
  );
}
