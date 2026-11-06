import { useRef, useState } from "react";
import { Search, Upload, X } from "lucide-react";
import { c, fs, ui } from "../../theme.js";
import { fieldBox, uiText } from "../../styles.js";

// A search box with a magnifier and a clear button. Esc clears it, or leaves it when it's already empty.
// inputRef: for focusing it from outside (optional). style: the box's place on the page (width, margins).
export function SearchBox({ value, onChange, placeholder, label, testId, clearTestId, inputRef, style }) {
  const ownRef = useRef(null);
  const ref = inputRef || ownRef;
  return (
    <div style={{ position: "relative", ...style }}>
      <Search size={15} color={c.textFaint} style={{ position: "absolute", left: 11, top: 10, pointerEvents: "none" }} />
      <input
        ref={ref}
        data-testid={testId}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            if (value) onChange("");
            else e.currentTarget.blur();
          }
        }}
        placeholder={placeholder}
        aria-label={label}
        autoComplete="off"
        spellCheck={false}
        style={{ ...fieldBox(), width: "100%", boxSizing: "border-box", padding: "8px 34px 8px 34px" }}
      />
      {value && (
        <button
          data-testid={clearTestId}
          onClick={() => {
            onChange("");
            ref.current?.focus();
          }}
          aria-label="Clear search"
          title="Clear search (Esc)"
          style={{ position: "absolute", right: 6, top: 6, width: 24, height: 24, display: "flex", alignItems: "center", justifyContent: "center", background: "none", border: "none", color: c.textMuted, cursor: "pointer", padding: 0 }}
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
}

// Where a file picked or dropped with a folder was in it ("Shark/Fins/Fin.stl"), or just its name
export const folderPathOf = (f) => f.folderPath || f.webkitRelativePath || f.name;

// Every file in what was dropped, folders read all the way down, each with its folderPath ("Shark/Fins/Fin.stl")
async function droppedFiles(entries) {
  const fileOf = (entry) =>
    new Promise((resolve) =>
      entry.file(
        (f) => {
          f.folderPath = entry.fullPath.replace(/^\/+/, "");
          resolve([f]);
        },
        () => resolve([])
      )
    );
  const inside = async (dir) => {
    const reader = dir.createReader();
    const all = [];
    for (;;) {
      // a folder is read a batch at a time, until an empty one
      const batch = await new Promise((resolve) => reader.readEntries(resolve, () => resolve([])));
      if (!batch.length) return all;
      all.push(...batch);
    }
  };
  const out = [];
  for (const entry of entries) {
    if (entry.isFile) out.push(...(await fileOf(entry)));
    else if (entry.isDirectory) out.push(...(await droppedFiles(await inside(entry))));
  }
  return out;
}

// `multiple`: several files can be picked or dropped at once, and `file` / `onFile` are a list of them instead.
// `folders` (with `multiple`): a folder can be dropped or chosen too, and every file in it and the folders inside it is
// taken, each knowing where it was (folderPathOf).
export function Dropzone({ label, compact = false, onFile, file, accept, multiple = false, folders = false }) {
  const inputRef = useRef(null);
  const folderRef = useRef(null);
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
    if (multiple && folders && e.dataTransfer.items?.length) {
      // read the entries now: they're gone once this event is over
      const entries = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
      droppedFiles(entries).then((all) => {
        const taken = all.filter((f) => accepts(f.name));
        if (taken.length) onFile?.(taken);
      });
      return;
    }
    if (multiple) {
      const dropped = [...(e.dataTransfer.files || [])].filter((f) => accepts(f.name));
      if (dropped.length) onFile?.(dropped);
      return;
    }
    const dropped = e.dataTransfer.files?.[0];
    if (!dropped) return;
    if (!accepts(dropped.name)) return;
    onFile?.(dropped);
  };
  const picked = multiple ? (file?.length ? file : null) : file;
  const names = (list) => (list.length > 6 ? `${list.slice(0, 5).map((f) => f.name).join(", ")} and ${list.length - 5} more` : list.map((f) => f.name).join(", "));
  const pickedName = !picked ? null : !multiple ? picked.name : picked.length === 1 ? picked[0].name : `${picked.length} files: ${names(picked)}`;

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={handleDragOver}
      onDragEnter={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        border: `1.5px dashed ${isDragging ? c.amber : picked ? c.teal : c.borderStrong}`,
        borderRadius: 4,
        padding: compact ? "14px 16px" : "26px 16px",
        textAlign: "center",
        color: picked ? c.textPrimary : c.textFaint,
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
        multiple={multiple}
        onChange={(e) => onFile?.(multiple ? [...(e.target.files || [])] : e.target.files?.[0] || null)}
        style={{ display: "none" }}
      />
      {folders && (
        <input
          ref={folderRef}
          type="file"
          webkitdirectory=""
          multiple
          onChange={(e) => {
            const taken = [...(e.target.files || [])].filter((f) => accepts(f.name));
            if (taken.length) onFile?.(taken);
          }}
          style={{ display: "none" }}
        />
      )}
      <Upload size={compact ? 14 : 20} color={isDragging ? c.amber : picked ? c.teal : c.textFaint} style={{ marginBottom: compact ? 0 : 8 }} />
      <div style={{ wordBreak: "break-word" }}>{picked ? pickedName : isDragging ? (multiple ? "Drop them" : "Drop it") : label}</div>
      {folders && !isDragging && (
        <button
          type="button"
          data-testid="dropzone-choose-folder"
          onClick={(e) => {
            e.stopPropagation(); // not the file picker as well
            folderRef.current?.click();
          }}
          style={{ ...ui, fontSize: fs(12), background: "none", border: "none", color: c.amber, textDecoration: "underline", cursor: "pointer", marginTop: 6, padding: 0 }}
        >
          or choose a folder
        </button>
      )}
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
