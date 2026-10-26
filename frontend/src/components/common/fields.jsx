import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { c, fs, ui } from "../../theme.js";
import { uiText } from "../../styles.js";

export function Dropzone({ label, compact = false, onFile, file, accept }) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  // Matching against `accept` ourselves: browsers don't enforce the
  // input's accept attribute on a programmatic drop, only on the native
  // file picker, so a dropped file needs the same check applied by hand.
  const accepts = (filename) => {
    if (!accept) return true;
    const exts = accept.split(",").map((s) => s.trim().toLowerCase());
    const name = filename.toLowerCase();
    return exts.some((ext) => name.endsWith(ext));
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };
  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (!dropped) return;
    if (!accepts(dropped.name)) return;
    onFile?.(dropped);
  };

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={handleDragOver}
      onDragEnter={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        border: `1.5px dashed ${isDragging ? c.amber : file ? c.teal : c.borderStrong}`,
        borderRadius: 4,
        padding: compact ? "14px 16px" : "26px 16px",
        textAlign: "center",
        color: file ? c.textPrimary : c.textFaint,
        background: isDragging ? c.amberDim : "transparent",
        ...ui,
        fontSize: fs(13),
        marginBottom: 14,
        display: "flex",
        flexDirection: compact ? "row" : "column",
        alignItems: "center",
        justifyContent: "center",
        gap: compact ? 8 : 0,
        cursor: "pointer",
        transition: "background 0.1s ease, border-color 0.1s ease",
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={(e) => onFile?.(e.target.files?.[0] || null)}
        style={{ display: "none" }}
      />
      <Upload size={compact ? 14 : 20} color={isDragging ? c.amber : file ? c.teal : c.textFaint} style={{ marginBottom: compact ? 0 : 8 }} />
      <div>{file ? file.name : isDragging ? "Drop it" : label}</div>
    </div>
  );
}

export function FieldSelect({ label, options, placeholder, value, onChange }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={uiText(12, c.textFaint, { marginBottom: 5 })}>{label}</div>
      <select
        value={value ?? ""}
        onChange={(e) => onChange?.(e.target.value)}
        style={{
          width: "100%",
          background: c.panelAlt,
          border: `1px solid ${c.border}`,
          borderRadius: 4,
          color: c.textPrimary,
          padding: "8px 10px",
          fontSize: fs(13),
          ...ui,
        }}
      >
        <option value="" disabled>
          {placeholder}
        </option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function SegmentedToggle({ options, value, onChange }) {
  return (
    <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          style={{
            ...ui,
            fontSize: fs(12),
            padding: "6px 12px",
            borderRadius: 4,
            cursor: "pointer",
            border: `1px solid ${value === o.value ? c.amber : c.border}`,
            background: value === o.value ? c.amberDim : "transparent",
            color: value === o.value ? c.amber : c.textMuted,
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function TextField({ label, value, onChange, placeholder, type = "text", disabled = false }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={uiText(12, c.textFaint, { marginBottom: 5 })}>{label}</div>
      <input
        type={type}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={type === "password" ? "new-password" : "off"}
        style={{
          width: "100%",
          background: c.panelAlt,
          border: `1px solid ${c.border}`,
          borderRadius: 4,
          color: c.textPrimary,
          padding: "8px 10px",
          fontSize: fs(13),
          opacity: disabled ? 0.6 : 1,
          ...ui,
        }}
      />
    </div>
  );
}
